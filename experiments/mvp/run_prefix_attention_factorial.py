#!/usr/bin/env python3
"""Rep 16: 2x2 causal dissection of the user-start prefix.

Factor the protocol prefix into the `<|im_start|>` special marker and the literal
`user` role label. Hold user content and assistant/Answer boundary fixed. Measure
candidate surfaces plus attention routing in heads localized by Rep 15.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import time
from pathlib import Path
from typing import Any

import torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer

import run_activation_poke as poke
import run_rep as base

TARGET_HEADS = [(14, 1), (17, 3), (18, 6), (18, 7), (18, 8)]
CONDITIONS = {
    "neither": {"marker": 0, "role": 0},
    "marker-only": {"marker": 1, "role": 0},
    "role-only": {"marker": 0, "role": 1},
    "both": {"marker": 1, "role": 1},
}


def now() -> float:
    return time.perf_counter()


def render(user: str, marker: int, role: int) -> str:
    if marker and role:
        prefix = "<|im_start|>user\n"
    elif marker:
        prefix = "<|im_start|>\n"
    elif role:
        prefix = "user\n"
    else:
        prefix = ""
    return f"{prefix}{user}\n{poke.ANSWER_TAIL}"


def locate(haystack: list[int], needle: list[int], *, last: bool = False) -> int:
    starts = [
        i for i in range(len(haystack) - len(needle) + 1)
        if haystack[i : i + len(needle)] == needle
    ]
    if not starts:
        raise RuntimeError(f"token subsequence not found: {needle}")
    return starts[-1] if last else starts[0]


def region_positions(tokenizer: Any, user: str, prompt: str) -> dict[str, list[int]]:
    ids = tokenizer(prompt, add_special_tokens=True).input_ids
    user_ids = tokenizer(user, add_special_tokens=False).input_ids
    tail_ids = tokenizer(poke.ANSWER_TAIL, add_special_tokens=False).input_ids
    user_start = locate(ids, user_ids)
    tail_start = locate(ids, tail_ids, last=True)
    user_pos = list(range(user_start, user_start + len(user_ids)))
    boundary_pos = list(range(tail_start, tail_start + len(tail_ids)))
    control_prefix = list(range(0, user_start))
    if control_prefix and tokenizer.bos_token_id is not None and ids[control_prefix[0]] == tokenizer.bos_token_id:
        control_prefix = control_prefix[1:]
    bos_pos = [0] if tokenizer.bos_token_id is not None and ids and ids[0] == tokenizer.bos_token_id else []
    return {
        "user-content": user_pos,
        "answer-boundary": boundary_pos,
        "control-prefix": control_prefix,
        "bos": bos_pos,
    }


def candidate_correct_margin(surface: dict[str, Any]) -> float:
    correct = surface["correct_candidate"]
    scores = {x["candidate"]: float(x["mean_logprob"]) for x in surface["candidate_scores"]}
    return scores[correct] - max(v for k, v in scores.items() if k != correct)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/prefix-attention-factorial.json"))
    args = parser.parse_args()

    started_wall, started = time.time(), now()
    timings: dict[str, float] = {}
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    torch.manual_seed(0)

    t = now()
    model_dir = Path(snapshot_download(
        repo_id=base.MODEL_REPO,
        revision=base.MODEL_REVISION,
        allow_patterns=base.MODEL_FILES,
        local_dir="/tmp/model-spelunker-smollm2",
    )).resolve()
    timings["hydrate_seconds"] = now() - t

    t = now()
    manifest_digest, files = base.content_manifest(model_dir)
    timings["artifact_verify_seconds"] = now() - t

    t = now()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir,
        local_files_only=True,
        torch_dtype=torch.float32,
        attn_implementation="eager",
    )
    model.eval()
    timings["model_load_seconds"] = now() - t

    observations = []
    head_factor_rows: dict[tuple[int, int], list[dict[str, dict[str, float]]]] = {h: [] for h in TARGET_HEADS}
    condition_behavior: dict[str, list[dict[str, float]]] = {name: [] for name in CONDITIONS}
    prefix_tokenization: dict[str, Any] = {}
    t = now()

    for task_index, task in enumerate(poke.HELDOUT):
        task_conditions: dict[str, Any] = {}
        for name, factors in CONDITIONS.items():
            prompt = render(task["user"], factors["marker"], factors["role"])
            encoded = tokenizer(prompt, return_tensors="pt")
            regions = region_positions(tokenizer, task["user"], prompt)
            with torch.inference_mode():
                out = model(**encoded, output_attentions=True, use_cache=False)
            if out.attentions is None:
                raise RuntimeError("attention output unavailable")

            surface = poke.condition_surface(model, tokenizer, prompt, task["candidates"], task["correct"])
            margin = candidate_correct_margin(surface)
            condition_behavior[name].append({
                "correct_top1": float(surface["correct_top1"]),
                "correct_rank": float(surface["correct_rank"]),
                "correct_margin": margin,
            })

            if task_index == 0:
                ids = encoded.input_ids[0].tolist()
                prefix_ids = [ids[i] for i in regions["control-prefix"]]
                prefix_tokenization[name] = {
                    "marker": factors["marker"],
                    "role": factors["role"],
                    "control_prefix_token_ids": prefix_ids,
                    "control_prefix_tokens": tokenizer.convert_ids_to_tokens(prefix_ids),
                    "control_prefix_decoded": tokenizer.decode(prefix_ids, skip_special_tokens=False),
                }

            head_metrics = {}
            final_q = int(encoded.input_ids.shape[1]) - 1
            for layer, head in TARGET_HEADS:
                attn = out.attentions[layer][0, head].detach().float().cpu()
                metric = {
                    "user_mass": float(attn[final_q, regions["user-content"]].sum().item()),
                    "boundary_mass": float(attn[final_q, regions["answer-boundary"]].sum().item()),
                    "control_prefix_mass": float(attn[final_q, regions["control-prefix"]].sum().item()) if regions["control-prefix"] else 0.0,
                    "bos_mass": float(attn[final_q, regions["bos"]].sum().item()) if regions["bos"] else 0.0,
                }
                head_metrics[f"L{layer}H{head}"] = metric

            task_conditions[name] = {
                "marker": factors["marker"],
                "role": factors["role"],
                "prompt_sha256": "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "input_token_ids_sha256": base.token_hash(encoded.input_ids),
                "input_tokens": int(encoded.input_ids.numel()),
                "region_token_counts": {k: len(v) for k, v in regions.items()},
                "candidate_surface": {k: v for k, v in surface.items() if k != "final_hidden"},
                "correct_margin": margin,
                "head_metrics": head_metrics,
            }

        for layer, head in TARGET_HEADS:
            key = f"L{layer}H{head}"
            per_condition = {name: task_conditions[name]["head_metrics"][key] for name in CONDITIONS}
            head_factor_rows[(layer, head)].append(per_condition)

        observations.append({
            "task_id": task["task_id"],
            "user_sha256": "sha256:" + hashlib.sha256(task["user"].encode("utf-8")).hexdigest(),
            "correct": task["correct"],
            "conditions": task_conditions,
        })

    timings["experiment_seconds"] = now() - t

    def factor_effect(values: dict[str, float]) -> dict[str, float]:
        marker = ((values["both"] + values["marker-only"]) - (values["role-only"] + values["neither"])) / 2.0
        role = ((values["both"] + values["role-only"]) - (values["marker-only"] + values["neither"])) / 2.0
        interaction = (values["both"] - values["marker-only"]) - (values["role-only"] - values["neither"])
        return {"marker_main_effect": marker, "role_main_effect": role, "interaction": interaction}

    head_summary = []
    for (layer, head), task_rows in sorted(head_factor_rows.items()):
        summary: dict[str, Any] = {"layer": layer, "head": head, "n": len(task_rows)}
        for metric_name in ("user_mass", "boundary_mass", "control_prefix_mass", "bos_mass"):
            means = {
                condition: sum(row[condition][metric_name] for row in task_rows) / len(task_rows)
                for condition in CONDITIONS
            }
            summary[metric_name + "_means"] = means
            summary[metric_name + "_factor_effects"] = factor_effect(means)
        head_summary.append(summary)

    behavior_summary = {}
    for name, rows in condition_behavior.items():
        behavior_summary[name] = {
            "n": len(rows),
            "top1_rate": sum(x["correct_top1"] for x in rows) / len(rows),
            "mean_correct_rank": sum(x["correct_rank"] for x in rows) / len(rows),
            "mean_correct_margin": sum(x["correct_margin"] for x in rows) / len(rows),
        }

    behavior_factor_effects = {
        metric: factor_effect({name: behavior_summary[name][metric] for name in CONDITIONS})
        for metric in ("top1_rate", "mean_correct_rank", "mean_correct_margin")
    }

    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(started_wall)}")
    git_sha = os.environ.get("GITHUB_SHA")
    artifact_provenance = {
        "tracked": True,
        "foundry_repository": "SemperSupra/model-artifact-foundry",
        "logical_artifact_id": base.LOGICAL_ID,
        "upstream_provider": "huggingface",
        "upstream_repository": base.MODEL_REPO,
        "upstream_revision": base.MODEL_REVISION,
        "identity_kind": "content-manifest",
        "identity_digest": manifest_digest,
        "foundry_record_ref": None,
        "consumer_selection_ref": f"model-spelunker@{git_sha}" if git_sha else None,
        "verified": True,
        "verification_ref": "foundry-compatible-local-content-manifest",
        "tokenizer_artifact": None,
    }
    observation_hash = "sha256:" + hashlib.sha256(
        json.dumps(observations, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    bundle = {
        "probe_id": "prefix-attention-factorial-v1",
        "instrument": "protocol-prefix-factorial-attention-localization",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": base.MODEL_REPO, "revision": base.MODEL_REVISION, "logical_id": base.LOGICAL_ID},
        "artifact_provenance": artifact_provenance,
        "access_tier": "A2",
        "evidence_level": "CAUSAL",
        "claim_tags": ["LOCALIZED"],
        "observations": {"heldout_tasks": observations, "prefix_tokenization": prefix_tokenization},
        "derived_metrics": {
            "head_factor_summary": head_summary,
            "behavior_summary": behavior_summary,
            "behavior_factor_effects": behavior_factor_effects,
            "target_heads": [{"layer": l, "head": h} for l, h in TARGET_HEADS],
            "content_manifest_file_count": len(files),
        },
        "artifacts": [],
        "uncertainty": {
            "status": "causal-input-factor-localization",
            "notes": ["The factorial causally localizes prefix components, but attention-head contribution remains relational until head-level intervention."]
        },
        "known_assumptions": [
            "The marker-only and role-only synthetic prefixes are interpretable factorial perturbations of the native prefix.",
            "The shared user content and assistant/Answer boundary remain semantically comparable across conditions."
        ],
        "known_failure_modes": [
            "Factorial synthetic prefixes are out-of-distribution relative to the native chat template.",
            "A factor that changes attention routing need not be sufficient for downstream behavioral change."
        ],
        "contradictions": [],
        "cost": {
            **timings,
            "total_seconds": now() - started,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "disk_free_mib_after": (os.statvfs('/tmp').f_bavail * os.statvfs('/tmp').f_frsize) / (1024 * 1024),
        },
        "provenance": {
            "run_id": str(run_id),
            "code_revision": git_sha,
            "model_revision": base.MODEL_REVISION,
            "tokenizer_revision": base.MODEL_REVISION,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "torch": torch.__version__,
                "transformers": __import__("transformers").__version__,
                "attention_implementation": "eager",
                "model_source": "upstream-exact-revision",
                "github_runner_image": os.environ.get("ImageOS"),
                "github_runner_arch": os.environ.get("RUNNER_ARCH"),
            },
            "randomness": {"torch_manual_seed": 0, "generation": "none"},
            "raw_input_hash": None,
            "raw_output_hash": observation_hash,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_id": str(run_id),
        "artifact_identity": manifest_digest,
        "tasks": len(observations),
        "target_heads": len(TARGET_HEADS),
        "behavior_summary": behavior_summary,
        "total_seconds": bundle["cost"]["total_seconds"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
