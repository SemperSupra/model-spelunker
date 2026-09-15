#!/usr/bin/env python3
"""Rep 18: fixed-layout attention-sink token identity panel.

Screen a preregistered set of one-token prefixes on already-observed calibration
probes, freeze that ranking, and evaluate the same panel on separately specified
holdout probes. All lexical/special panel conditions use exactly one prefix token
followed by a common newline. L18H8 prefix-attention mass is retained as a sink
engagement sanity check; downstream behavior is scored separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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

PANEL_CANDIDATES = [
    {"panel_id": "neutral-x", "literal": "x", "category": "neutral"},
    {"panel_id": "neutral-foo", "literal": "foo", "category": "neutral"},
    {"panel_id": "article-the", "literal": "the", "category": "common-word"},
    {"panel_id": "role-user", "literal": "user", "category": "role"},
    {"panel_id": "letter-A", "literal": "A", "category": "symbol"},
    {"panel_id": "digit-0", "literal": "0", "category": "symbol"},
    {"panel_id": "period", "literal": ".", "category": "punctuation"},
    {"panel_id": "question", "literal": "?", "category": "punctuation"},
    {"panel_id": "affirm-yes", "literal": "yes", "category": "semantic"},
    {"panel_id": "negate-no", "literal": "no", "category": "semantic"},
    {"panel_id": "special-im-start", "literal": "<|im_start|>", "category": "special"},
]

HOLDOUT = [
    {
        "task_id": "hold-mul-8x9",
        "user": "Compute 8 x 9.",
        "correct": "72",
        "candidates": ["64", "70", "72", "81", "88"],
    },
    {
        "task_id": "hold-sub-31-14",
        "user": "Compute 31 - 14.",
        "correct": "17",
        "candidates": ["15", "16", "17", "18", "19"],
    },
    {
        "task_id": "hold-capital-japan",
        "user": "What is the capital of Japan?",
        "correct": "Tokyo",
        "candidates": ["Tokyo", "Kyoto", "Osaka", "Seoul", "Beijing"],
    },
    {
        "task_id": "hold-red-planet",
        "user": "Which planet is known as the Red Planet?",
        "correct": "Mars",
        "candidates": ["Mars", "Venus", "Jupiter", "Mercury", "Saturn"],
    },
    {
        "task_id": "hold-month-before-april",
        "user": "Which month comes immediately before April?",
        "correct": "March",
        "candidates": ["January", "February", "March", "May", "June"],
    },
    {
        "task_id": "hold-decimal-larger",
        "user": "Which number is larger, 0.42 or 0.37?",
        "correct": "0.42",
        "candidates": ["0.32", "0.37", "0.40", "0.42", "0.47"],
    },
]

ATTENTION_LAYER = 18
ATTENTION_HEAD = 8


def now() -> float:
    return time.perf_counter()


def locate(haystack: list[int], needle: list[int]) -> int:
    starts = [i for i in range(len(haystack) - len(needle) + 1) if haystack[i:i+len(needle)] == needle]
    if not starts:
        raise RuntimeError(f"subsequence not found: {needle}")
    return starts[0]


def prefix_region(tokenizer: Any, user: str, prompt: str) -> list[int]:
    ids = tokenizer(prompt, add_special_tokens=True).input_ids
    user_ids = tokenizer(user, add_special_tokens=False).input_ids
    u0 = locate(ids, user_ids)
    return list(range(0, u0))


def correct_margin(surface: dict[str, Any]) -> float:
    correct = surface["correct_candidate"]
    scores = {x["candidate"]: float(x["mean_logprob"]) for x in surface["candidate_scores"]}
    return scores[correct] - max(v for k, v in scores.items() if k != correct)


def rank_values(values: dict[str, float]) -> dict[str, int]:
    # Deterministic descending ranks; ties broken by panel id.
    ordered = sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))
    return {name: i + 1 for i, (name, _) in enumerate(ordered)}


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    if denom <= 1e-12:
        return None
    return sum(x*y for x, y in zip(dx, dy)) / denom


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/sink-token-panel.json"))
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

    eligible = []
    ineligible = []
    for item in PANEL_CANDIDATES:
        token_ids = tokenizer(item["literal"], add_special_tokens=False).input_ids
        record = {**item, "token_ids": [int(x) for x in token_ids], "tokens": tokenizer.convert_ids_to_tokens(token_ids)}
        if len(token_ids) == 1:
            record["token_id"] = int(token_ids[0])
            record["decoded"] = tokenizer.decode(token_ids, skip_special_tokens=False)
            eligible.append(record)
        else:
            ineligible.append(record)
    if len(eligible) < 6:
        raise RuntimeError(f"too few preregistered one-token prefixes survived: {len(eligible)}")

    conditions = [
        {"panel_id": "baseline-none", "kind": "baseline", "prefix": "", "token_id": None},
        {"panel_id": "baseline-newline", "kind": "sink-baseline", "prefix": "\n", "token_id": None},
    ] + [
        {"panel_id": x["panel_id"], "kind": "one-token", "prefix": x["literal"] + "\n", "token_id": x["token_id"], "category": x["category"]}
        for x in eligible
    ]

    task_sets = {"calibration": poke.HELDOUT, "holdout": HOLDOUT}
    observations: dict[str, list[dict[str, Any]]] = {"calibration": [], "holdout": []}
    aggregate: dict[str, dict[str, list[float]]] = {
        c["panel_id"]: {"cal_margin": [], "cal_top1": [], "hold_margin": [], "hold_top1": [], "sink_mass": []}
        for c in conditions
    }
    t = now()

    for split, tasks in task_sets.items():
        for task in tasks:
            task_conditions = {}
            for condition in conditions:
                prompt = f"{condition['prefix']}{task['user']}\n{poke.ANSWER_TAIL}"
                encoded = tokenizer(prompt, return_tensors="pt")
                surface = poke.condition_surface(model, tokenizer, prompt, task["candidates"], task["correct"])
                margin = correct_margin(surface)

                with torch.inference_mode():
                    attn_out = model(**encoded, output_attentions=True, use_cache=False)
                attn = attn_out.attentions[ATTENTION_LAYER][0, ATTENTION_HEAD].detach().float().cpu()
                q = int(encoded.input_ids.shape[1]) - 1
                prefix_pos = prefix_region(tokenizer, task["user"], prompt)
                sink_mass = float(attn[q, prefix_pos].sum().item()) if prefix_pos else 0.0

                bucket = aggregate[condition["panel_id"]]
                if split == "calibration":
                    bucket["cal_margin"].append(margin)
                    bucket["cal_top1"].append(float(surface["correct_top1"]))
                else:
                    bucket["hold_margin"].append(margin)
                    bucket["hold_top1"].append(float(surface["correct_top1"]))
                if condition["panel_id"] != "baseline-none":
                    bucket["sink_mass"].append(sink_mass)

                task_conditions[condition["panel_id"]] = {
                    "kind": condition["kind"],
                    "token_id": condition.get("token_id"),
                    "category": condition.get("category"),
                    "prompt_sha256": "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "input_tokens": int(encoded.input_ids.numel()),
                    "candidate_surface": {k: v for k, v in surface.items() if k != "final_hidden"},
                    "correct_margin": margin,
                    "l18h8_prefix_attention_mass": sink_mass,
                }

            observations[split].append({
                "task_id": task["task_id"],
                "user_sha256": "sha256:" + hashlib.sha256(task["user"].encode("utf-8")).hexdigest(),
                "correct": task["correct"],
                "conditions": task_conditions,
            })

    timings["experiment_seconds"] = now() - t

    panel_summary = {}
    for condition in conditions:
        pid = condition["panel_id"]
        a = aggregate[pid]
        panel_summary[pid] = {
            "kind": condition["kind"],
            "token_id": condition.get("token_id"),
            "category": condition.get("category"),
            "calibration_top1_rate": sum(a["cal_top1"]) / len(a["cal_top1"]),
            "calibration_mean_margin": sum(a["cal_margin"]) / len(a["cal_margin"]),
            "holdout_top1_rate": sum(a["hold_top1"]) / len(a["hold_top1"]),
            "holdout_mean_margin": sum(a["hold_margin"]) / len(a["hold_margin"]),
            "mean_sink_mass": (sum(a["sink_mass"]) / len(a["sink_mass"])) if a["sink_mass"] else 0.0,
        }

    calibration_values = {
        pid: row["calibration_mean_margin"]
        for pid, row in panel_summary.items()
        if row["kind"] == "one-token"
    }
    holdout_values = {
        pid: row["holdout_mean_margin"]
        for pid, row in panel_summary.items()
        if row["kind"] == "one-token"
    }
    calibration_rank = rank_values(calibration_values)
    holdout_rank = rank_values(holdout_values)
    frozen_top3 = [pid for pid, _ in sorted(calibration_values.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    baseline_hold_margin = panel_summary["baseline-newline"]["holdout_mean_margin"]
    transfer = {
        pid: {
            "calibration_rank": calibration_rank[pid],
            "holdout_rank": holdout_rank[pid],
            "calibration_mean_margin": calibration_values[pid],
            "holdout_mean_margin": holdout_values[pid],
            "holdout_margin_delta_vs_newline": holdout_values[pid] - baseline_hold_margin,
            "frozen_top3": pid in frozen_top3,
        }
        for pid in calibration_values
    }
    rank_corr = pearson(
        [float(calibration_rank[pid]) for pid in sorted(calibration_rank)],
        [float(holdout_rank[pid]) for pid in sorted(calibration_rank)],
    )
    value_corr = pearson(
        [calibration_values[pid] for pid in sorted(calibration_values)],
        [holdout_values[pid] for pid in sorted(calibration_values)],
    )

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
        "probe_id": "sink-token-identity-panel-v1",
        "instrument": "attention-sink-token-identity-screen-holdout",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": base.MODEL_REPO, "revision": base.MODEL_REVISION, "logical_id": base.LOGICAL_ID},
        "artifact_provenance": artifact_provenance,
        "access_tier": "A2",
        "evidence_level": "PREDICTIVE",
        "claim_tags": ["LOCALIZED"],
        "observations": {
            "calibration_tasks": observations["calibration"],
            "holdout_tasks": observations["holdout"],
            "eligible_panel": eligible,
            "ineligible_preregistered_panel": ineligible,
        },
        "derived_metrics": {
            "panel_summary": panel_summary,
            "calibration_rank": calibration_rank,
            "holdout_rank": holdout_rank,
            "frozen_calibration_top3": frozen_top3,
            "transfer": transfer,
            "calibration_holdout_rank_correlation": rank_corr,
            "calibration_holdout_margin_correlation": value_corr,
            "attention_sanity_head": {"layer": ATTENTION_LAYER, "head": ATTENTION_HEAD},
            "content_manifest_file_count": len(files),
        },
        "artifacts": [],
        "uncertainty": {
            "status": "small-panel-predictive-screen",
            "notes": [
                "Holdout tasks were specified in code before calibration ranking was observed.",
                "This small task set can identify promising token-identity transfer but cannot establish a general capability recipe."
            ]
        },
        "known_assumptions": [
            "Eligible panel strings that tokenize to one token are comparable under the common one-token-plus-newline layout.",
            "L18H8 near-saturated prefix attention is an attention-sink engagement check, not a capability metric."
        ],
        "known_failure_modes": [
            "Token frequency, embedding norm, semantic content, and training-template frequency remain confounded within token identity.",
            "Multiple token candidates are screened; any later promotion requires frozen-candidate replication on new holdouts."
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
        "eligible_tokens": len(eligible),
        "ineligible_tokens": len(ineligible),
        "frozen_top3": frozen_top3,
        "rank_correlation": rank_corr,
        "margin_correlation": value_corr,
        "total_seconds": bundle["cost"]["total_seconds"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
