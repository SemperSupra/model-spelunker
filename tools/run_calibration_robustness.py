#!/usr/bin/env python3
"""Multi-stem calibration robustness check for Experiment 0001.

This is a falsification instrument, not a benchmark. It asks whether the semantic
continuation result survives multiple language-matched neutral stems and held-out
reciprocity cases. It also records token/character/byte representation costs so
cross-language differences are not silently interpreted as concept effects.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch
from huggingface_hub import model_info
from transformers import AutoModelForCausalLM, AutoTokenizer

from run_calibrated_semantic_smoke import conditional_mean_logprob, read_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        default="fixtures/experiment-0001/reciprocity-semantic-heldout.jsonl",
    )
    parser.add_argument("--model", default="EleutherAI/pythia-70m")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--output-dir", default="artifacts/experiment-0001-robustness")
    return parser.parse_args()


def text_metrics(tokenizer: AutoTokenizer, text: str) -> dict[str, float | int]:
    tokens = len(tokenizer(text, add_special_tokens=False).input_ids)
    chars = len(text)
    nonspace = sum(1 for char in text if not char.isspace())
    utf8_bytes = len(text.encode("utf-8"))
    return {
        "tokens": tokens,
        "unicode_chars": chars,
        "nonspace_chars": nonspace,
        "utf8_bytes": utf8_bytes,
        "tokens_per_unicode_char": tokens / max(1, chars),
        "tokens_per_nonspace_char": tokens / max(1, nonspace),
        "tokens_per_utf8_byte": tokens / max(1, utf8_bytes),
    }


def score_probe(
    model: AutoModelForCausalLM,
    tokenizer: AutoTokenizer,
    probe: dict[str, Any],
) -> dict[str, Any]:
    candidates = {
        "positive": probe["positive_continuation"],
        "negative": probe["negative_continuation"],
    }
    stems = probe.get("neutral_prompts")
    if not stems:
        if "neutral_prompt" not in probe:
            raise ValueError(f"{probe['surface_id']} has no neutral calibration stem")
        stems = [probe["neutral_prompt"]]
    if len(stems) < 2:
        raise ValueError(
            f"{probe['surface_id']} needs at least two neutral stems for robustness testing"
        )

    prompted: dict[str, float] = {}
    prompted_tokens: dict[str, int] = {}
    for name, continuation in candidates.items():
        score, count = conditional_mean_logprob(model, tokenizer, probe["prompt"], continuation)
        prompted[name] = score
        prompted_tokens[name] = count

    stem_records: list[dict[str, Any]] = []
    deltas_by_candidate: dict[str, list[float]] = {name: [] for name in candidates}
    for index, stem in enumerate(stems):
        neutral: dict[str, float] = {}
        calibrated: dict[str, float] = {}
        neutral_tokens: dict[str, int] = {}
        for name, continuation in candidates.items():
            score, count = conditional_mean_logprob(model, tokenizer, stem, continuation)
            neutral[name] = score
            neutral_tokens[name] = count
            calibrated[name] = prompted[name] - score
            deltas_by_candidate[name].append(calibrated[name])

        selected = max(calibrated, key=calibrated.get)
        other = "negative" if selected == "positive" else "positive"
        stem_records.append(
            {
                "stem_index": index,
                "neutral_prompt": stem,
                "neutral_mean_logprob": neutral,
                "neutral_candidate_token_counts": neutral_tokens,
                "calibrated_delta": calibrated,
                "selected": selected,
                "margin": calibrated[selected] - calibrated[other],
                "neutral_prompt_metrics": text_metrics(tokenizer, stem),
            }
        )

    aggregate_delta = {
        name: mean(values) for name, values in deltas_by_candidate.items()
    }
    aggregate_selected = max(aggregate_delta, key=aggregate_delta.get)
    aggregate_other = "negative" if aggregate_selected == "positive" else "positive"
    selections = [record["selected"] for record in stem_records]
    selection_counts = Counter(selections)
    mode_count = max(selection_counts.values())
    expected = probe.get("expected")

    return {
        "concept_id": probe["concept_id"],
        "probe_id": probe["probe_id"],
        "surface_id": probe["surface_id"],
        "class": probe["class"],
        "language": probe["language"],
        "source": probe["source"],
        "translation_path": probe.get("translation_path"),
        "expected": expected,
        "aggregate_selected": aggregate_selected,
        "score": None if expected is None else float(aggregate_selected == expected),
        "aggregate_delta": aggregate_delta,
        "aggregate_margin": aggregate_delta[aggregate_selected] - aggregate_delta[aggregate_other],
        "stem_count": len(stems),
        "stem_selection_counts": dict(selection_counts),
        "stem_selection_stability": mode_count / len(stems),
        "stem_selection_unanimous": len(selection_counts) == 1,
        "stem_records": stem_records,
        "prompted_mean_logprob": prompted,
        "prompted_candidate_token_counts": prompted_tokens,
        "prompt_metrics": text_metrics(tokenizer, probe["prompt"]),
        "candidate_metrics": {
            name: text_metrics(tokenizer, continuation) for name, continuation in candidates.items()
        },
    }


def language_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in rows if row["score"] is not None]
    return {
        "n": len(rows),
        "accuracy": None if not labeled else mean(row["score"] for row in labeled),
        "stem_unanimous_rate": mean(float(row["stem_selection_unanimous"]) for row in rows),
        "mean_stem_stability": mean(row["stem_selection_stability"] for row in rows),
        "mean_input_tokens": mean(row["prompt_metrics"]["tokens"] for row in rows),
        "mean_tokens_per_nonspace_char": mean(
            row["prompt_metrics"]["tokens_per_nonspace_char"] for row in rows
        ),
        "mean_tokens_per_utf8_byte": mean(
            row["prompt_metrics"]["tokens_per_utf8_byte"] for row in rows
        ),
        "selection_counts": dict(Counter(row["aggregate_selected"] for row in rows)),
    }


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))

    fixture_path = Path(args.fixture)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    probes = read_jsonl(fixture_path)
    rng.shuffle(probes)

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(f"Could not resolve immutable revision for {args.model}@{args.revision}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=resolved_revision)
    model.eval()
    model.to("cpu")

    rows: list[dict[str, Any]] = []
    records_path = output_dir / "calibration-robustness-records.jsonl"
    with records_path.open("w", encoding="utf-8") as handle:
        for probe in probes:
            row = score_probe(model, tokenizer, probe)
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                json.dumps(
                    {
                        "surface_id": row["surface_id"],
                        "selected": row["aggregate_selected"],
                        "expected": row["expected"],
                        "score": row["score"],
                        "stem_stability": round(row["stem_selection_stability"], 3),
                        "unanimous": row["stem_selection_unanimous"],
                        "input_tokens": row["prompt_metrics"]["tokens"],
                    },
                    ensure_ascii=False,
                )
            )

    labeled = [row for row in rows if row["score"] is not None]
    by_language: dict[str, Any] = {}
    for language in sorted({row["language"] for row in rows}):
        by_language[language] = language_summary(
            [row for row in rows if row["language"] == language]
        )

    by_probe_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_probe_id[row["probe_id"]].append(row)
    cross_language_groups = [group for group in by_probe_id.values() if len(group) > 1]
    cross_language_unanimous = [
        group
        for group in cross_language_groups
        if len({row["aggregate_selected"] for row in group}) == 1
    ]

    summary = {
        "model": args.model,
        "requested_revision": args.revision,
        "resolved_revision": resolved_revision,
        "fixture": str(fixture_path),
        "seed": args.seed,
        "probe_count": len(rows),
        "accuracy": None if not labeled else mean(row["score"] for row in labeled),
        "stem_unanimous_rate": mean(float(row["stem_selection_unanimous"]) for row in rows),
        "mean_stem_stability": mean(row["stem_selection_stability"] for row in rows),
        "cross_language_group_count": len(cross_language_groups),
        "cross_language_unanimous_rate": (
            None
            if not cross_language_groups
            else len(cross_language_unanimous) / len(cross_language_groups)
        ),
        "by_language": by_language,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
