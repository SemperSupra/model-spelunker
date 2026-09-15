#!/usr/bin/env python3
"""Rep 19: preregistered replication of frozen attention-sink token A.

Rep 18 froze `A` (token 49) before this task set was evaluated. This rep compares
A against newline-only plus B, x, and user controls on an entirely new 16-task
holdout. Primary endpoint is mean correct-answer margin; rank/top-1 and per-task
adverse shifts are secondary. L18H8 prefix attention is retained as a sink sanity
check, not as the primary endpoint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

import torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer

import run_activation_poke as poke
import run_rep as base

CONDITIONS = [
    {"condition_id": "baseline-newline", "literal": "", "expected_token_id": None, "role": "baseline"},
    {"condition_id": "frozen-A", "literal": "A", "expected_token_id": 49, "role": "frozen-candidate"},
    {"condition_id": "letter-B", "literal": "B", "expected_token_id": None, "role": "letter-control"},
    {"condition_id": "neutral-x", "literal": "x", "expected_token_id": 104, "role": "neutral-control"},
    {"condition_id": "role-user", "literal": "user", "expected_token_id": 4093, "role": "role-control"},
]

HOLDOUT = [
    {"task_id":"rep19-mul-12x7","user":"Compute 12 x 7.","correct":"84","candidates":["72","77","84","91","96"]},
    {"task_id":"rep19-sub-45-19","user":"Compute 45 - 19.","correct":"26","candidates":["24","25","26","27","28"]},
    {"task_id":"rep19-add-16-27","user":"Compute 16 + 27.","correct":"43","candidates":["41","42","43","44","45"]},
    {"task_id":"rep19-div-81-9","user":"Compute 81 divided by 9.","correct":"9","candidates":["7","8","9","10","11"]},
    {"task_id":"rep19-capital-canada","user":"What is the capital of Canada?","correct":"Ottawa","candidates":["Ottawa","Toronto","Montreal","Vancouver","Calgary"]},
    {"task_id":"rep19-largest-ocean","user":"Which is the largest ocean on Earth?","correct":"Pacific","candidates":["Pacific","Atlantic","Indian","Arctic","Southern"]},
    {"task_id":"rep19-plant-gas","user":"Which gas do plants absorb from the air for photosynthesis?","correct":"carbon dioxide","candidates":["oxygen","nitrogen","carbon dioxide","hydrogen","helium"]},
    {"task_id":"rep19-first-month","user":"Which month is the first month of the year?","correct":"January","candidates":["January","February","March","April","December"]},
    {"task_id":"rep19-after-september","user":"Which month comes immediately after September?","correct":"October","candidates":["August","September","October","November","December"]},
    {"task_id":"rep19-rings","user":"Which planet is famous for its prominent rings?","correct":"Saturn","candidates":["Mars","Earth","Jupiter","Saturn","Venus"]},
    {"task_id":"rep19-water-boil","user":"At standard pressure, what is the boiling point of water in degrees Celsius?","correct":"100","candidates":["0","50","90","100","212"]},
    {"task_id":"rep19-binary-five","user":"What is the binary representation of decimal 5?","correct":"101","candidates":["100","101","110","111","1000"]},
    {"task_id":"rep19-decimal-larger","user":"Which number is larger, 0.58 or 0.63?","correct":"0.63","candidates":["0.53","0.58","0.60","0.63","0.68"]},
    {"task_id":"rep19-prime","user":"Which of these numbers is prime?","correct":"23","candidates":["21","22","23","24","25"]},
    {"task_id":"rep19-day-after-monday","user":"Which day comes immediately after Monday?","correct":"Tuesday","candidates":["Sunday","Monday","Tuesday","Wednesday","Thursday"]},
    {"task_id":"rep19-gold-symbol","user":"What is the chemical symbol for gold?","correct":"Au","candidates":["Ag","Au","Fe","Go","Gd"]},
]

ATTENTION_LAYER = 18
ATTENTION_HEAD = 8
ADVERSE_MARGIN_THRESHOLD = 0.25


def now() -> float:
    return time.perf_counter()


def correct_margin(surface: dict[str, Any]) -> float:
    correct = surface["correct_candidate"]
    scores = {x["candidate"]: float(x["mean_logprob"]) for x in surface["candidate_scores"]}
    return scores[correct] - max(v for k, v in scores.items() if k != correct)


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def rank_from_surface(surface: dict[str, Any]) -> int:
    return int(surface["correct_rank"])


def prefix_positions(tokenizer: Any, user: str, prompt: str) -> list[int]:
    ids = tokenizer(prompt, add_special_tokens=True).input_ids
    user_ids = tokenizer(user, add_special_tokens=False).input_ids
    starts = [i for i in range(len(ids) - len(user_ids) + 1) if ids[i:i+len(user_ids)] == user_ids]
    if not starts:
        raise RuntimeError("user token subsequence not found")
    return list(range(starts[0]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/sink-token-replication.json"))
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

    resolved_conditions = []
    for cond in CONDITIONS:
        if cond["condition_id"] == "baseline-newline":
            resolved_conditions.append({**cond, "token_id": None, "token_ids": []})
            continue
        ids = tokenizer(cond["literal"], add_special_tokens=False).input_ids
        if len(ids) != 1:
            raise RuntimeError(f"{cond['condition_id']} must be exactly one token, got {ids}")
        token_id = int(ids[0])
        if cond["expected_token_id"] is not None and token_id != cond["expected_token_id"]:
            raise RuntimeError(f"token identity drift for {cond['condition_id']}: {token_id} != {cond['expected_token_id']}")
        resolved_conditions.append({**cond, "token_id": token_id, "token_ids": [token_id]})

    aggregate = {
        c["condition_id"]: {"margins": [], "ranks": [], "top1": [], "sink_mass": []}
        for c in resolved_conditions
    }
    observations = []
    t = now()
    for task in HOLDOUT:
        task_rows = {}
        for cond in resolved_conditions:
            prefix = "\n" if cond["condition_id"] == "baseline-newline" else cond["literal"] + "\n"
            prompt = f"{prefix}{task['user']}\n{poke.ANSWER_TAIL}"
            encoded = tokenizer(prompt, return_tensors="pt")
            surface = poke.condition_surface(model, tokenizer, prompt, task["candidates"], task["correct"])
            margin = correct_margin(surface)
            with torch.inference_mode():
                out = model(**encoded, output_attentions=True, use_cache=False)
            attn = out.attentions[ATTENTION_LAYER][0, ATTENTION_HEAD].detach().float().cpu()
            q = int(encoded.input_ids.shape[1]) - 1
            ppos = prefix_positions(tokenizer, task["user"], prompt)
            sink_mass = float(attn[q, ppos].sum().item()) if ppos else 0.0

            b = aggregate[cond["condition_id"]]
            b["margins"].append(margin)
            b["ranks"].append(float(rank_from_surface(surface)))
            b["top1"].append(float(surface["correct_top1"]))
            b["sink_mass"].append(sink_mass)
            task_rows[cond["condition_id"]] = {
                "token_id": cond["token_id"],
                "role": cond["role"],
                "prompt_sha256": "sha256:" + hashlib.sha256(prompt.encode()).hexdigest(),
                "correct_margin": margin,
                "correct_rank": rank_from_surface(surface),
                "correct_top1": bool(surface["correct_top1"]),
                "l18h8_prefix_attention_mass": sink_mass,
                "candidate_surface": {k: v for k, v in surface.items() if k != "final_hidden"},
            }
        observations.append({
            "task_id": task["task_id"],
            "user_sha256": "sha256:" + hashlib.sha256(task["user"].encode()).hexdigest(),
            "correct": task["correct"],
            "conditions": task_rows,
        })
    timings["experiment_seconds"] = now() - t

    summary = {}
    for cid, b in aggregate.items():
        summary[cid] = {
            "n": len(b["margins"]),
            "mean_correct_margin": mean(b["margins"]),
            "mean_correct_rank": mean(b["ranks"]),
            "top1_rate": mean(b["top1"]),
            "mean_sink_mass": mean(b["sink_mass"]),
        }

    baseline_margins = aggregate["baseline-newline"]["margins"]
    a_margins = aggregate["frozen-A"]["margins"]
    task_deltas = [a - b for a, b in zip(a_margins, baseline_margins)]
    primary = {
        "frozen_candidate": "frozen-A",
        "baseline": "baseline-newline",
        "mean_margin_delta": mean(task_deltas),
        "positive_margin_delta_tasks": sum(x > 0 for x in task_deltas),
        "negative_margin_delta_tasks": sum(x < 0 for x in task_deltas),
        "adverse_gt_threshold_tasks": sum(x < -ADVERSE_MARGIN_THRESHOLD for x in task_deltas),
        "adverse_margin_threshold": ADVERSE_MARGIN_THRESHOLD,
        "top1_rate_delta": summary["frozen-A"]["top1_rate"] - summary["baseline-newline"]["top1_rate"],
        "mean_rank_delta": summary["frozen-A"]["mean_correct_rank"] - summary["baseline-newline"]["mean_correct_rank"],
    }

    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(started_wall)}")
    git_sha = os.environ.get("GITHUB_SHA")
    bundle = {
        "probe_id": "sink-token-frozen-A-replication-v1",
        "instrument": "attention-sink-token-identity-preregistered-replication",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": base.MODEL_REPO, "revision": base.MODEL_REVISION, "logical_id": base.LOGICAL_ID},
        "artifact_provenance": {
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
        },
        "access_tier": "A2",
        "evidence_level": "PREDICTIVE",
        "claim_tags": ["LOCALIZED"],
        "observations": {"holdout_tasks": observations, "conditions": resolved_conditions},
        "derived_metrics": {
            "condition_summary": summary,
            "primary_A_vs_newline": primary,
            "task_margin_deltas_A_vs_newline": dict(zip([t["task_id"] for t in HOLDOUT], task_deltas)),
            "content_manifest_file_count": len(files),
        },
        "artifacts": [],
        "uncertainty": {
            "status": "preregistered-frozen-candidate-replication",
            "notes": [
                "A/token 49 was frozen by Rep 18 before any Rep 19 task outcome was observed.",
                "Primary endpoint is mean correct-answer margin delta versus newline-only; top-1/rank are secondary.",
            ],
        },
        "known_assumptions": ["All nonbaseline controls are exactly one tokenizer token followed by newline."],
        "known_failure_modes": ["A margin benefit without top-1 benefit is a decision-surface effect, not a demonstrated capability uplift."],
        "contradictions": [],
        "cost": {
            **timings,
            "total_seconds": now() - started,
            "peak_rss_mib": poke.peak_rss_mib(),
            "disk_free_mib_after": poke.disk_free_mib(Path("/tmp")),
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
                "github_runner_image": os.environ.get("ImageOS"),
                "github_runner_arch": os.environ.get("RUNNER_ARCH"),
            },
            "randomness": {"torch_manual_seed": 0},
            "raw_input_hash": "sha256:" + hashlib.sha256(json.dumps(HOLDOUT, sort_keys=True).encode()).hexdigest(),
            "raw_output_hash": "sha256:" + hashlib.sha256(json.dumps(observations, sort_keys=True).encode()).hexdigest(),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_id": str(run_id),
        "artifact_identity": manifest_digest,
        "tasks": len(HOLDOUT),
        "primary": primary,
        "condition_summary": summary,
        "total_seconds": bundle["cost"]["total_seconds"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
