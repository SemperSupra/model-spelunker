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
from transformers import (
    AutoConfig,
    AutoModelForCausalLM,
    AutoModelForImageTextToText,
    AutoTokenizer,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", default="main")
    parser.add_argument(
        "--dtype",
        choices=("float32", "bfloat16", "float16", "auto"),
        default="float32",
        help="Model load dtype. bfloat16 is useful for larger CPU qualification reps.",
    )
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def continuation_text(language: str, candidate: str) -> str:
    return candidate if language == "th" else f" {candidate}"


def candidate_logprob_scores(
    hf_model,
    tokenizer,
    prompt: str,
    language: str,
    candidates: list[str],
) -> list[dict[str, Any]]:
    """Score forced-choice continuations by mean token log probability."""
    prompt_ids = tokenizer(prompt, add_special_tokens=False).input_ids
    rows: list[dict[str, Any]] = []
    max_len = 0
    for candidate in candidates:
        continuation = continuation_text(language, candidate)
        full_ids = tokenizer(prompt + continuation, add_special_tokens=False).input_ids
        if full_ids[: len(prompt_ids)] != prompt_ids:
            raise ValueError(
                f"Tokenizer prefix changed when appending candidate {candidate!r}"
            )
        start = len(prompt_ids)
        if len(full_ids) <= start:
            raise ValueError(f"Candidate produced no continuation tokens: {candidate!r}")
        rows.append(
            {
                "candidate": candidate,
                "input_ids": full_ids,
                "start": start,
                "continuation_token_count": len(full_ids) - start,
            }
        )
        max_len = max(max_len, len(full_ids))

    pad_id = tokenizer.pad_token_id
    if pad_id is None:
        pad_id = tokenizer.eos_token_id
    if pad_id is None:
        raise ValueError("Tokenizer has neither pad_token_id nor eos_token_id")

    batch_ids = torch.full(
        (len(rows), max_len), int(pad_id), dtype=torch.long, device="cpu"
    )
    attention = torch.zeros_like(batch_ids)
    for i, row in enumerate(rows):
        ids = torch.tensor(row["input_ids"], dtype=torch.long)
        batch_ids[i, : len(ids)] = ids
        attention[i, : len(ids)] = 1

    with torch.inference_mode():
        logits = hf_model(
            input_ids=batch_ids, attention_mask=attention, use_cache=False
        ).logits.float()
        log_probs = torch.log_softmax(logits, dim=-1)

    scored: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        ids = row["input_ids"]
        start = int(row["start"])
        token_logps: list[float] = []
        for pos in range(start, len(ids)):
            if pos == 0:
                raise ValueError("Cannot score continuation token at absolute position 0")
            token_logps.append(float(log_probs[i, pos - 1, ids[pos]].item()))
        scored.append(
            {
                "candidate": row["candidate"],
                "continuation_token_count": row["continuation_token_count"],
                "sum_logprob": float(sum(token_logps)),
                "mean_logprob": float(sum(token_logps) / len(token_logps)),
            }
        )
    return scored


def resolve_dtype(name: str):
    if name == "auto":
        return "auto"
    return {
        "float32": torch.float32,
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
    }[name]


def load_model(model_name: str, revision: str, dtype):
    config = AutoConfig.from_pretrained(model_name, revision=revision)
    architectures = list(getattr(config, "architectures", None) or [])
    kwargs = {
        "revision": revision,
        "dtype": dtype,
        "low_cpu_mem_usage": True,
    }
    if any(name.endswith("ForConditionalGeneration") for name in architectures):
        model = AutoModelForImageTextToText.from_pretrained(model_name, **kwargs)
        loader = "AutoModelForImageTextToText"
    else:
        model = AutoModelForCausalLM.from_pretrained(model_name, **kwargs)
        loader = "AutoModelForCausalLM"
    return model, loader, architectures


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
    hf_model, loader, architectures = load_model(
        args.model, resolved_revision, resolve_dtype(args.dtype)
    )
    hf_model.eval().to("cpu")

    records: list[dict[str, Any]] = []
    print(
        f"model={args.model} revision={resolved_revision} "
        f"class={hf_model.__class__.__name__} loader={loader} dtype={args.dtype} "
        f"cases={len(cases)} behavior_only=true"
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
        "model_loader": loader,
        "model_architectures": architectures,
        "requested_revision": args.revision,
        "resolved_model_revision": resolved_revision,
        "load_dtype": args.dtype,
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
