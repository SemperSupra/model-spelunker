#!/usr/bin/env python3
"""Cheap behavior-only preflight for Experiment 0002 bridge tasks.

This intentionally omits Jacobian-lens loading and hidden-state observation.
Its only job is to decide whether a model has enough clean downstream behavior
to justify spending a later rep on observer and causal interventions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch
from huggingface_hub import model_info
from transformers import AutoModelForCausalLM, AutoTokenizer

from run_multilingual_bridge_cloze import candidate_logprob_scores, read_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))
    cases = read_jsonl(Path(args.fixture))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(
            f"Could not resolve immutable revision for {args.model}@{args.revision}"
        )

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    hf_model = AutoModelForCausalLM.from_pretrained(
        args.model, revision=resolved_revision, dtype=torch.float32
    )
    hf_model.eval().to("cpu")

    records: list[dict[str, Any]] = []
    print(
        f"model={args.model} revision={resolved_revision} "
        f"class={hf_model.__class__.__name__} cases={len(cases)} behavior_only=true"
    )

    for case in cases:
        candidate_scores = candidate_logprob_scores(
            hf_model,
            tokenizer,
            case["prompt"],
            case["language"],
            case["answer_candidates"],
        )
        ordered = sorted(
            candidate_scores, key=lambda row: row["mean_logprob"], reverse=True
        )
        predicted = ordered[0]["candidate"]
        correct = predicted == case["correct_answer"]
        correct_row = next(
            row for row in candidate_scores
            if row["candidate"] == case["correct_answer"]
        )
        behavior_margin = correct_row["mean_logprob"] - max(
            row["mean_logprob"]
            for row in candidate_scores
            if row["candidate"] != case["correct_answer"]
        )
        input_tokens = len(
            tokenizer(case["prompt"], add_special_tokens=False).input_ids
        )
        record = {
            "case_id": case["case_id"],
            "concept_id": case["concept_id"],
            "language": case["language"],
            "prompt_sha256": hashlib.sha256(
                case["prompt"].encode("utf-8")
            ).hexdigest(),
            "input_tokens": input_tokens,
            "correct_answer": case["correct_answer"],
            "answer_candidates": case["answer_candidates"],
            "candidate_scores": candidate_scores,
            "predicted_answer": predicted,
            "behavior_correct": correct,
            "behavior_margin_mean_logprob": behavior_margin,
        }
        records.append(record)
        print(
            json.dumps(
                {
                    "case_id": record["case_id"],
                    "language": record["language"],
                    "predicted": predicted,
                    "correct": case["correct_answer"],
                    "behavior_ok": correct,
                    "behavior_margin": behavior_margin,
                },
                ensure_ascii=False,
            )
        )

    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_language[row["language"]].append(row)

    language_summary: dict[str, Any] = {}
    for language, rows in sorted(by_language.items()):
        language_summary[language] = {
            "n": len(rows),
            "behavior_accuracy": sum(row["behavior_correct"] for row in rows)
            / max(1, len(rows)),
            "median_behavior_margin": float(
                median(row["behavior_margin_mean_logprob"] for row in rows)
            ),
        }

    summary = {
        "experiment": "0002-multilingual-bridge-behavior-preflight",
        "model": args.model,
        "model_class": hf_model.__class__.__name__,
        "requested_revision": args.revision,
        "resolved_model_revision": resolved_revision,
        "case_count": len(cases),
        "evaluated_cases": len(records),
        "behavior_accuracy": sum(row["behavior_correct"] for row in records)
        / max(1, len(records)),
        "language_summary": language_summary,
        "interpretation": (
            "behavior-only qualification. Passing this gate only earns a later "
            "observer/causal rep; it is not representation evidence."
        ),
    }

    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
