#!/usr/bin/env python3
"""Rep 17: neutral-prefix challenge for the prefix-sensitive attention sink.

Test whether neutral text prefixes reproduce the routing effect seen for `user` and
`<|im_start|>`. This distinguishes a general first-prefix/position sink from a
semantic protocol-control effect.
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
PREFIXES = {
    "none": "",
    "newline": "\n",
    "neutral-x": "x\n",
    "neutral-foo": "foo\n",
    "role-user": "user\n",
    "role-assistant": "assistant\n",
    "special-marker": "<|im_start|>\n",
}


def now() -> float:
    return time.perf_counter()


def locate(haystack: list[int], needle: list[int], *, last: bool = False) -> int:
    starts = [i for i in range(len(haystack) - len(needle) + 1) if haystack[i:i+len(needle)] == needle]
    if not starts:
        raise RuntimeError(f"token subsequence not found: {needle}")
    return starts[-1] if last else starts[0]


def regions(tokenizer: Any, user: str, prompt: str) -> dict[str, list[int]]:
    ids = tokenizer(prompt, add_special_tokens=True).input_ids
    user_ids = tokenizer(user, add_special_tokens=False).input_ids
    tail_ids = tokenizer(poke.ANSWER_TAIL, add_special_tokens=False).input_ids
    u0 = locate(ids, user_ids)
    t0 = locate(ids, tail_ids, last=True)
    return {
        "prefix": list(range(0, u0)),
        "user": list(range(u0, u0 + len(user_ids))),
        "boundary": list(range(t0, t0 + len(tail_ids))),
    }


def correct_margin(surface: dict[str, Any]) -> float:
    correct = surface["correct_candidate"]
    scores = {x["candidate"]: float(x["mean_logprob"]) for x in surface["candidate_scores"]}
    return scores[correct] - max(v for k, v in scores.items() if k != correct)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/neutral-prefix-challenge.json"))
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
    condition_rows: dict[str, list[dict[str, float]]] = {name: [] for name in PREFIXES}
    head_rows: dict[tuple[int, int, str], list[dict[str, float]]] = {}
    prefix_tokenization: dict[str, Any] = {}
    t = now()

    for task_index, task in enumerate(poke.HELDOUT):
        task_conditions = {}
        for name, prefix in PREFIXES.items():
            prompt = f"{prefix}{task['user']}\n{poke.ANSWER_TAIL}"
            encoded = tokenizer(prompt, return_tensors="pt")
            r = regions(tokenizer, task["user"], prompt)
            with torch.inference_mode():
                out = model(**encoded, output_attentions=True, use_cache=False)
            if out.attentions is None:
                raise RuntimeError("attention output unavailable")

            surface = poke.condition_surface(model, tokenizer, prompt, task["candidates"], task["correct"])
            margin = correct_margin(surface)
            condition_rows[name].append({
                "top1": float(surface["correct_top1"]),
                "rank": float(surface["correct_rank"]),
                "margin": margin,
            })

            if task_index == 0:
                ids = encoded.input_ids[0].tolist()
                prefix_ids = [ids[i] for i in r["prefix"]]
                prefix_tokenization[name] = {
                    "literal_prefix": prefix,
                    "prefix_token_ids": prefix_ids,
                    "prefix_tokens": tokenizer.convert_ids_to_tokens(prefix_ids),
                    "prefix_decoded": tokenizer.decode(prefix_ids, skip_special_tokens=False),
                }

            head_metrics = {}
            q = int(encoded.input_ids.shape[1]) - 1
            for layer, head in TARGET_HEADS:
                attn = out.attentions[layer][0, head].detach().float().cpu()
                m = {
                    "prefix_mass": float(attn[q, r["prefix"]].sum().item()) if r["prefix"] else 0.0,
                    "user_mass": float(attn[q, r["user"]].sum().item()),
                    "boundary_mass": float(attn[q, r["boundary"]].sum().item()),
                }
                head_metrics[f"L{layer}H{head}"] = m
                head_rows.setdefault((layer, head, name), []).append(m)

            task_conditions[name] = {
                "prompt_sha256": "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "input_tokens": int(encoded.input_ids.numel()),
                "prefix_token_count": len(r["prefix"]),
                "candidate_surface": {k: v for k, v in surface.items() if k != "final_hidden"},
                "correct_margin": margin,
                "head_metrics": head_metrics,
            }

        observations.append({
            "task_id": task["task_id"],
            "user_sha256": "sha256:" + hashlib.sha256(task["user"].encode("utf-8")).hexdigest(),
            "correct": task["correct"],
            "conditions": task_conditions,
        })

    timings["experiment_seconds"] = now() - t

    condition_summary = {}
    for name, rows in condition_rows.items():
        condition_summary[name] = {
            "n": len(rows),
            "top1_rate": sum(x["top1"] for x in rows) / len(rows),
            "mean_correct_rank": sum(x["rank"] for x in rows) / len(rows),
            "mean_correct_margin": sum(x["margin"] for x in rows) / len(rows),
        }

    head_summary = []
    for layer, head in TARGET_HEADS:
        per_condition = {}
        for name in PREFIXES:
            rows = head_rows[(layer, head, name)]
            per_condition[name] = {
                "mean_prefix_mass": sum(x["prefix_mass"] for x in rows) / len(rows),
                "mean_user_mass": sum(x["user_mass"] for x in rows) / len(rows),
                "mean_boundary_mass": sum(x["boundary_mass"] for x in rows) / len(rows),
            }
        head_summary.append({"layer": layer, "head": head, "conditions": per_condition})

    tokenizer_meta = {
        "bos_token": tokenizer.bos_token,
        "bos_token_id": tokenizer.bos_token_id,
        "eos_token": tokenizer.eos_token,
        "eos_token_id": tokenizer.eos_token_id,
        "all_special_tokens": tokenizer.all_special_tokens,
        "all_special_ids": tokenizer.all_special_ids,
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
        "probe_id": "neutral-prefix-challenge-v1",
        "instrument": "prefix-content-attention-sink-challenge",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": base.MODEL_REPO, "revision": base.MODEL_REVISION, "logical_id": base.LOGICAL_ID},
        "artifact_provenance": artifact_provenance,
        "access_tier": "A2",
        "evidence_level": "CAUSAL",
        "claim_tags": ["LOCALIZED"],
        "observations": {
            "heldout_tasks": observations,
            "prefix_tokenization": prefix_tokenization,
            "tokenizer_metadata": tokenizer_meta,
        },
        "derived_metrics": {
            "condition_summary": condition_summary,
            "head_condition_summary": head_summary,
            "target_heads": [{"layer": l, "head": h} for l, h in TARGET_HEADS],
            "content_manifest_file_count": len(files),
        },
        "artifacts": [],
        "uncertainty": {
            "status": "causal-prefix-specificity-challenge",
            "notes": ["Neutral prefixes test specificity of the sink; downstream head causality remains unproven without direct head intervention."]
        },
        "known_assumptions": [
            "The neutral and role prefixes are useful matched perturbations even when exact token identities differ.",
            "Prefix attention mass from the final answer query is a descriptive routing measure, not by itself a causal contribution score."
        ],
        "known_failure_modes": [
            "Token-count and token-identity differences between prefixes can confound pure semantic interpretation.",
            "Synthetic prefixes may be out-of-distribution relative to training templates."
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
        "conditions": len(PREFIXES),
        "behavior": condition_summary,
        "tokenizer_bos": {"token": tokenizer.bos_token, "id": tokenizer.bos_token_id},
        "total_seconds": bundle["cost"]["total_seconds"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
