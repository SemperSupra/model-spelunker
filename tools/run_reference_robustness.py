#!/usr/bin/env python3
"""Reference-CPU repeatability gate for Experiment 0001.

Runs the held-out multi-stem reciprocity instrument repeatedly on one runner using
conservative numeric settings. Cross-run comparison is still required, but this
first proves that one host/process is internally repeatable and captures enough
runtime provenance to diagnose host-dependent drift.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from reference_cpu import (
    NUMERIC_MODE,
    configure_reference_cpu,
    prepare_reference_model,
    runtime_fingerprint,
)

import huggingface_hub
import transformers
from huggingface_hub import model_info
from transformers import AutoModelForCausalLM, AutoTokenizer

from run_calibration_robustness import language_summary, read_jsonl, score_probe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        default="fixtures/experiment-0001/reciprocity-semantic-heldout.jsonl",
    )
    parser.add_argument("--model", default="EleutherAI/pythia-70m")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output-dir", default="artifacts/experiment-0001-reference")
    return parser.parse_args()


def signed_margin(row: dict[str, Any]) -> float:
    return row["aggregate_delta"]["positive"] - row["aggregate_delta"]["negative"]


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in rows if row["score"] is not None]
    by_language: dict[str, Any] = {}
    for language in sorted({row["language"] for row in rows}):
        by_language[language] = language_summary(
            [row for row in rows if row["language"] == language]
        )

    by_probe_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_probe_id[row["probe_id"]].append(row)
    groups = [group for group in by_probe_id.values() if len(group) > 1]
    unanimous_groups = [
        group for group in groups if len({row["aggregate_selected"] for row in group}) == 1
    ]

    return {
        "probe_count": len(rows),
        "accuracy": None if not labeled else mean(row["score"] for row in labeled),
        "stem_unanimous_rate": mean(float(row["stem_selection_unanimous"]) for row in rows),
        "mean_stem_stability": mean(row["stem_selection_stability"] for row in rows),
        "cross_language_group_count": len(groups),
        "cross_language_unanimous_rate": (
            None if not groups else len(unanimous_groups) / len(groups)
        ),
        "by_language": by_language,
    }


def compare_repeats(repeats: list[list[dict[str, Any]]]) -> dict[str, Any]:
    maps = [
        {row["surface_id"]: row for row in rows}
        for rows in repeats
    ]
    surfaces = sorted(maps[0])
    if any(sorted(mapping) != surfaces for mapping in maps[1:]):
        raise ValueError("Repeat probe sets differ")

    per_probe: list[dict[str, Any]] = []
    all_drifts: list[float] = []
    stable_selections = 0
    for surface in surfaces:
        rows = [mapping[surface] for mapping in maps]
        margins = [signed_margin(row) for row in rows]
        selections = [row["aggregate_selected"] for row in rows]
        drift = max(margins) - min(margins)
        all_drifts.append(drift)
        stable = len(set(selections)) == 1
        stable_selections += int(stable)
        per_probe.append(
            {
                "surface_id": surface,
                "language": rows[0]["language"],
                "margins": margins,
                "margin_drift": drift,
                "selections": selections,
                "selection_stable": stable,
            }
        )

    return {
        "repeat_count": len(repeats),
        "selection_agreement_rate": stable_selections / len(surfaces),
        "max_margin_drift": max(all_drifts, default=0.0),
        "mean_margin_drift": mean(all_drifts) if all_drifts else 0.0,
        "exact_margin_repeatability": all(drift == 0.0 for drift in all_drifts),
        "per_probe": per_probe,
    }


def main() -> int:
    args = parse_args()
    if args.repeats < 2:
        raise ValueError("Reference repeatability gate requires at least two repeats")

    configure_reference_cpu(args.seed)
    fixture_path = Path(args.fixture)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    probes = read_jsonl(fixture_path)
    probes.sort(key=lambda probe: probe["surface_id"])

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(f"Could not resolve immutable revision for {args.model}@{args.revision}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=resolved_revision)
    prepare_reference_model(model)

    repeat_rows: list[list[dict[str, Any]]] = []
    for repeat_index in range(args.repeats):
        random.seed(args.seed)
        rows: list[dict[str, Any]] = []
        path = output_dir / f"repeat-{repeat_index + 1:02d}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for probe in probes:
                row = score_probe(model, tokenizer, probe)
                rows.append(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        repeat_rows.append(rows)

    repeatability = compare_repeats(repeat_rows)
    primary = summarize_rows(repeat_rows[0])
    summary = {
        "numeric_mode": NUMERIC_MODE,
        "model": args.model,
        "requested_revision": args.revision,
        "resolved_revision": resolved_revision,
        "fixture": str(fixture_path),
        "seed": args.seed,
        "runtime": runtime_fingerprint(),
        "packages": {
            "transformers": transformers.__version__,
            "huggingface_hub": huggingface_hub.__version__,
        },
        "primary": primary,
        "intra_runner_repeatability": repeatability,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if repeatability["selection_agreement_rate"] < 1.0:
        raise RuntimeError("Reference CPU selections were not repeatable within one runner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
