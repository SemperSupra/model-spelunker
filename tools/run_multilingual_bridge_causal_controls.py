#!/usr/bin/env python3
"""Experiment 0002: paired causal controls for the hidden-country bridge.

This wrapper exists to falsify two alternative explanations before the larger
all-target causal matrix is worth running:

1. target steering: does the counterfactual effect still occur when the source
   coordinate is an unrelated absent token rather than the actual hidden
   country?
2. observer non-uniqueness: does the same intervention work just as well using
   raw residual/unembedding directions, without Jacobian transport?

Only English and German are used here because the 0.8B model is behaviorally
competent and concept-specific on those surfaces. Thai remains a held-out stress
lane; this run is apparatus calibration, not a three-language Neuralese claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch
from huggingface_hub import hf_hub_download, model_info
from transformers import AutoModelForCausalLM, AutoTokenizer

import jlens
from jspace_interventions import jspace_swap
from run_multilingual_bridge_causal import (
    CONCEPT_IDS,
    DEFAULT_LENS_FILE,
    DEFAULT_LENS_REPO,
    DEFAULT_LENS_REVISION,
    DEFAULT_MODEL,
    JLENS_UPSTREAM_COMMIT,
    PAIRED_TARGET,
    enrich_result,
    parse_layers,
    score_candidates,
    single_token_id,
)
from run_multilingual_bridge_cloze import read_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        default="fixtures/experiment-0002/multilingual-indirect-bridge-cloze.jsonl",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--lens-repo", default=DEFAULT_LENS_REPO)
    parser.add_argument("--lens-revision", default=DEFAULT_LENS_REVISION)
    parser.add_argument("--lens-file", default=DEFAULT_LENS_FILE)
    parser.add_argument("--languages", default="en,de")
    parser.add_argument("--late-layers", default="18-22")
    parser.add_argument("--early-layers", default="0-4")
    parser.add_argument("--strength", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--absent-source-surface", default=" piano")
    parser.add_argument(
        "--output-dir",
        default="artifacts/experiment-0002-multilingual-bridge-causal-controls",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))
    languages = {value.strip() for value in args.languages.split(",") if value.strip()}
    late_layers = parse_layers(args.late_layers)
    early_layers = parse_layers(args.early_layers)
    cases = read_jsonl(Path(args.fixture))
    case_by_key = {(case["concept_id"], case["language"]): case for case in cases}
    selected = [
        case
        for case in cases
        if case["language"] in languages and case["concept_id"] in CONCEPT_IDS
    ]
    if not selected:
        raise ValueError("No cases selected for paired causal control")

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(f"Could not resolve immutable revision for {args.model}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    hf_model = AutoModelForCausalLM.from_pretrained(
        args.model, revision=resolved_revision, dtype=torch.float32
    )
    hf_model.eval().to("cpu")
    model = jlens.from_hf(hf_model, tokenizer)

    lens_path = hf_hub_download(
        repo_id=args.lens_repo,
        filename=args.lens_file,
        revision=args.lens_revision,
    )
    lens = jlens.JacobianLens.load(lens_path)
    if lens.d_model != model.d_model:
        raise ValueError(f"Lens/model width mismatch: {lens.d_model} != {model.d_model}")
    for layer in late_layers + early_layers:
        if layer not in lens.source_layers:
            raise ValueError(f"Requested layer {layer} not present in fitted lens")

    canonical_surface: dict[str, str] = {}
    canonical_token: dict[str, int] = {}
    for concept_id in CONCEPT_IDS:
        english_case = case_by_key[(concept_id, "en")]
        surface = english_case["intermediate_surfaces"][0]
        canonical_surface[concept_id] = surface
        canonical_token[concept_id] = single_token_id(tokenizer, surface)

    absent_token = single_token_id(tokenizer, args.absent_source_surface)
    if absent_token in canonical_token.values():
        raise ValueError("Absent-source token collides with a country coordinate")
    if any(args.absent_source_surface.strip().casefold() in case["prompt"].casefold() for case in selected):
        raise ValueError("Absent-source surface is present in a selected prompt")

    # (layers, intervention mode, source selector)
    conditions = {
        "late_jspace": (late_layers, "coordinate_swap", "actual"),
        "early_jspace": (early_layers, "coordinate_swap", "actual"),
        "late_random": (late_layers, "random_norm_matched", "actual"),
        "late_raw": (late_layers, "raw_coordinate_swap", "actual"),
        "late_absent_source": (late_layers, "coordinate_swap", "absent"),
    }

    baseline_by_case: dict[str, dict[str, Any]] = {}
    prompt_len_by_case: dict[str, int] = {}
    for case in selected:
        baseline_by_case[case["case_id"]] = score_candidates(hf_model, tokenizer, case)
        prompt_len_by_case[case["case_id"]] = len(
            tokenizer(case["prompt"], add_special_tokens=False).input_ids
        )

    records: list[dict[str, Any]] = []
    print(
        f"model={args.model} revision={resolved_revision} cases={len(selected)} "
        f"late={late_layers} early={early_layers} absent={args.absent_source_surface!r}",
        flush=True,
    )

    for case in selected:
        source_concept = case["concept_id"]
        target_concept = PAIRED_TARGET[source_concept]
        target_case = case_by_key[(target_concept, case["language"])]
        source_answer = case["correct_answer"]
        target_answer = target_case["correct_answer"]
        baseline_internal = baseline_by_case[case["case_id"]]
        baseline = {
            "predicted_answer": baseline_internal["predicted_answer"],
            "candidate_scores": baseline_internal["candidate_scores"],
        }
        prompt_len = prompt_len_by_case[case["case_id"]]

        row: dict[str, Any] = {
            "case_id": case["case_id"],
            "language": case["language"],
            "prompt_sha256": hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest(),
            "source_concept": source_concept,
            "target_concept": target_concept,
            "source_latent_surface": canonical_surface[source_concept],
            "target_latent_surface": canonical_surface[target_concept],
            "source_answer": source_answer,
            "target_answer": target_answer,
            "baseline": baseline,
            "conditions": {},
        }

        for name, (layers, mode, source_selector) in conditions.items():
            source_token = (
                canonical_token[source_concept]
                if source_selector == "actual"
                else absent_token
            )
            with jspace_swap(
                model,
                lens,
                source_token,
                canonical_token[target_concept],
                layers,
                strength=args.strength,
                mode=mode,
                seed=args.seed,
                key=f"{case['case_id']}|{target_concept}|{name}",
                position_limit=prompt_len,
            ):
                result = score_candidates(hf_model, tokenizer, case)
            result = enrich_result(
                result,
                baseline_internal,
                source_answer=source_answer,
                target_answer=target_answer,
            )
            result["layers"] = layers
            result["mode"] = mode
            result["source_selector"] = source_selector
            result["source_token_id"] = source_token
            result["strength"] = args.strength
            row["conditions"][name] = result

        actual = row["conditions"]["late_jspace"]
        absent = row["conditions"]["late_absent_source"]
        raw = row["conditions"]["late_raw"]
        random_control = row["conditions"]["late_random"]
        row["control_comparisons"] = {
            "actual_minus_absent_target_gain": (
                actual["intended_target_gain"] - absent["intended_target_gain"]
            ),
            "actual_minus_raw_target_gain": (
                actual["intended_target_gain"] - raw["intended_target_gain"]
            ),
            "actual_minus_random_target_gain": (
                actual["intended_target_gain"] - random_control["intended_target_gain"]
            ),
            "actual_source_outperforms_absent": (
                actual["intended_target_gain"] > absent["intended_target_gain"]
            ),
            "jspace_outperforms_raw": (
                actual["intended_target_gain"] > raw["intended_target_gain"]
            ),
            "actual_outperforms_random": (
                actual["intended_target_gain"] > random_control["intended_target_gain"]
            ),
            "source_specific_target_write": (
                actual["target_specificity_hit"]
                and actual["intended_target_gain"] > 0
                and actual["intended_target_gain"] > absent["intended_target_gain"]
            ),
            "jspace_specific_target_write": (
                actual["target_specificity_hit"]
                and actual["intended_target_gain"] > 0
                and actual["intended_target_gain"] > absent["intended_target_gain"]
                and actual["intended_target_gain"] > raw["intended_target_gain"]
            ),
        }
        records.append(row)

        print(
            json.dumps(
                {
                    "case_id": case["case_id"],
                    "language": case["language"],
                    "swap": f"{source_concept}->{target_concept}",
                    "baseline": baseline["predicted_answer"],
                    "target": target_answer,
                    "jspace_pred": actual["predicted_answer"],
                    "jspace_gain": actual["intended_target_gain"],
                    "absent_gain": absent["intended_target_gain"],
                    "raw_gain": raw["intended_target_gain"],
                    "random_gain": random_control["intended_target_gain"],
                    "source_specific": row["control_comparisons"]["source_specific_target_write"],
                    "jspace_specific": row["control_comparisons"]["jspace_specific_target_write"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    def summarize_condition(name: str) -> dict[str, Any]:
        values = [row["conditions"][name] for row in records]
        return {
            "n": len(values),
            "strong_causal_successes": sum(v["strong_causal_success"] for v in values),
            "preference_flips": sum(v["preference_flip"] for v in values),
            "target_specificity_hits": sum(v["target_specificity_hit"] for v in values),
            "target_specificity_rate": mean(float(v["target_specificity_hit"]) for v in values),
            "mean_intended_target_gain": mean(v["intended_target_gain"] for v in values),
            "median_intended_target_gain": median(v["intended_target_gain"] for v in values),
            "mean_margin_change": mean(v["margin_change_from_baseline"] for v in values),
        }

    comparisons = [row["control_comparisons"] for row in records]
    control_summary = {
        "actual_source_outperforms_absent": sum(v["actual_source_outperforms_absent"] for v in comparisons),
        "jspace_outperforms_raw": sum(v["jspace_outperforms_raw"] for v in comparisons),
        "actual_outperforms_random": sum(v["actual_outperforms_random"] for v in comparisons),
        "source_specific_target_writes": sum(v["source_specific_target_write"] for v in comparisons),
        "jspace_specific_target_writes": sum(v["jspace_specific_target_write"] for v in comparisons),
        "mean_actual_minus_absent_target_gain": mean(v["actual_minus_absent_target_gain"] for v in comparisons),
        "mean_actual_minus_raw_target_gain": mean(v["actual_minus_raw_target_gain"] for v in comparisons),
        "mean_actual_minus_random_target_gain": mean(v["actual_minus_random_target_gain"] for v in comparisons),
    }

    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_language[row["language"]].append(row)
    language_summary = {}
    for language, rows in sorted(by_language.items()):
        language_summary[language] = {
            "n": len(rows),
            "baseline_valid": sum(
                row["baseline"]["predicted_answer"] == row["source_answer"] for row in rows
            ),
            "jspace_target_specific": sum(
                row["conditions"]["late_jspace"]["target_specificity_hit"] for row in rows
            ),
            "source_specific_target_writes": sum(
                row["control_comparisons"]["source_specific_target_write"] for row in rows
            ),
            "jspace_specific_target_writes": sum(
                row["control_comparisons"]["jspace_specific_target_write"] for row in rows
            ),
        }

    summary = {
        "experiment": "0002-multilingual-hidden-bridge-causal-controls",
        "model": args.model,
        "resolved_model_revision": resolved_revision,
        "model_class": hf_model.__class__.__name__,
        "jlens_upstream_commit": JLENS_UPSTREAM_COMMIT,
        "lens_repo": args.lens_repo,
        "lens_revision": args.lens_revision,
        "lens_file": args.lens_file,
        "lens_n_prompts": lens.n_prompts,
        "languages": sorted(languages),
        "late_layers": late_layers,
        "early_layers": early_layers,
        "strength": args.strength,
        "case_count": len(records),
        "baseline_valid_count": sum(
            row["baseline"]["predicted_answer"] == row["source_answer"] for row in records
        ),
        "absent_source_surface": args.absent_source_surface,
        "canonical_latent_surfaces": canonical_surface,
        "conditions": {name: summarize_condition(name) for name in conditions},
        "control_comparisons": control_summary,
        "language_summary": language_summary,
        "promotion_rule": (
            "Do not promote to the full all-target matrix unless the actual-source J-space arm "
            "shows target-specific positive gain, beats the absent-source and norm-matched-random "
            "controls on most baseline-valid cases, and the raw-direction comparison is explicitly "
            "reported rather than silently treated as inferior."
        ),
        "interpretation": (
            "Paired causal apparatus calibration only. Source-specific effects support a causal "
            "hidden-state write; J-space-specific effects additionally require beating the raw "
            "residual/unembedding control. Neither outcome establishes a general Neuralese ontology."
        ),
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
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
