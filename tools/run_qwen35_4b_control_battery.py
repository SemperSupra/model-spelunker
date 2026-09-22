#!/usr/bin/env python3
"""Experiment 0002 R20: independent causal falsification battery.

Use four behavior-valid English capital cases and the frozen Qwen3.5-4B country
addresses. One model/lens load evaluates controls that falsify different causal
stories. Results are a vector, not a single omnibus pass/fail, so failures stay
legible rather than being averaged away.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from statistics import mean
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch
from huggingface_hub import hf_hub_download, model_info
from transformers import AutoModelForImageTextToText, AutoTokenizer

import jlens
from jspace_interventions import jspace_swap
from run_multilingual_bridge_cloze import read_jsonl
from run_qwen35_4b_cross_task_causal import (
    CONCEPT_IDS,
    DEFAULT_LENS_FILE,
    DEFAULT_LENS_REPO,
    DEFAULT_LENS_REVISION,
    DEFAULT_MODEL,
    JLENS_UPSTREAM_COMMIT,
    PAIRED_TARGET,
    enrich,
    one_token_id,
    score_candidates,
)

CAPITAL_FIXTURE = "fixtures/experiment-0002/multilingual-indirect-bridge-cloze.jsonl"
ABSENT_SURFACES = (" piano", " banana", " violin", " telescope")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", default="artifacts/experiment-0002-r20-control-battery")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = model_info(DEFAULT_MODEL, revision="main")
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError("Could not resolve immutable Qwen3.5-4B revision")
    tokenizer = AutoTokenizer.from_pretrained(DEFAULT_MODEL, revision=resolved_revision)
    hf_model = AutoModelForImageTextToText.from_pretrained(
        DEFAULT_MODEL,
        revision=resolved_revision,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    hf_model.eval().to("cpu")
    model = jlens.from_hf(hf_model, tokenizer)

    lens_path = hf_hub_download(
        repo_id=DEFAULT_LENS_REPO,
        filename=DEFAULT_LENS_FILE,
        revision=DEFAULT_LENS_REVISION,
    )
    lens = jlens.JacobianLens.load(lens_path)
    fitted_layers = sorted(int(layer) for layer in lens.source_layers)
    if len(fitted_layers) < 10:
        raise ValueError("R20 requires at least ten fitted source layers")
    early_layers = fitted_layers[:5]
    late_layers = fitted_layers[-5:]

    rows = [
        row for row in read_jsonl(Path(CAPITAL_FIXTURE))
        if row["language"] == "en" and row["concept_id"] in CONCEPT_IDS
    ]
    if len(rows) != 4:
        raise ValueError(f"Expected four English capital cases, got {len(rows)}")
    by_concept = {row["concept_id"]: row for row in rows}

    canonical_token: dict[str, int] = {}
    for concept_id, row in by_concept.items():
        canonical_token[concept_id] = one_token_id(tokenizer, row["intermediate_surfaces"][0])

    joined_prompts = " ".join(row["prompt"].lower() for row in rows)
    absent_surface = None
    absent_token = None
    for surface in ABSENT_SURFACES:
        if surface.strip().lower() in joined_prompts:
            continue
        ids = tokenizer(surface, add_special_tokens=False).input_ids
        if len(ids) == 1:
            absent_surface = surface
            absent_token = int(ids[0])
            break
    if absent_token is None:
        raise RuntimeError("No precommitted absent-source lexicalization is one token")

    baselines: dict[str, dict[str, Any]] = {}
    prompt_lengths: dict[str, int] = {}
    for case in rows:
        scored = score_candidates(hf_model, tokenizer, case)
        if scored["predicted_answer"] != case["correct_answer"]:
            raise RuntimeError(
                f"Behavior gate failed for {case['case_id']}: "
                f"{scored['predicted_answer']} != {case['correct_answer']}"
            )
        baselines[case["case_id"]] = scored
        prompt_lengths[case["case_id"]] = len(
            tokenizer(case["prompt"], add_special_tokens=False).input_ids
        )

    records: list[dict[str, Any]] = []
    for case in rows:
        case_id = case["case_id"]
        source_concept = case["concept_id"]
        target_concept = PAIRED_TARGET[source_concept]
        source_answer = case["correct_answer"]
        target_answer = by_concept[target_concept]["correct_answer"]
        source_id = canonical_token[source_concept]
        target_id = canonical_token[target_concept]
        prompt_len = prompt_lengths[case_id]
        base = baselines[case_id]

        condition_specs = {
            "primary": dict(mode="coordinate_swap", layers=late_layers, strength=1.0, source_id=source_id, start=0, stop=prompt_len),
            "random": dict(mode="random_norm_matched", layers=late_layers, strength=1.0, source_id=source_id, start=0, stop=prompt_len),
            "raw_residual": dict(mode="raw_coordinate_swap", layers=late_layers, strength=1.0, source_id=source_id, start=0, stop=prompt_len),
            "wrong_layer": dict(mode="coordinate_swap", layers=early_layers, strength=1.0, source_id=source_id, start=0, stop=prompt_len),
            "wrong_position": dict(mode="coordinate_swap", layers=late_layers, strength=1.0, source_id=source_id, start=0, stop=1),
            "reverse_sign": dict(mode="coordinate_swap", layers=late_layers, strength=-1.0, source_id=source_id, start=0, stop=prompt_len),
            "absent_source": dict(mode="coordinate_swap", layers=late_layers, strength=1.0, source_id=absent_token, start=0, stop=prompt_len),
            "dose_0_5": dict(mode="coordinate_swap", layers=late_layers, strength=0.5, source_id=source_id, start=0, stop=prompt_len),
            "dose_2_0": dict(mode="coordinate_swap", layers=late_layers, strength=2.0, source_id=source_id, start=0, stop=prompt_len),
        }
        conditions: dict[str, Any] = {}
        for name, spec in condition_specs.items():
            with jspace_swap(
                model,
                lens,
                spec["source_id"],
                target_id,
                spec["layers"],
                strength=spec["strength"],
                mode=spec["mode"],
                seed=1729,
                key=f"r20|{case_id}|{target_concept}|{name}",
                position_start=spec["start"],
                position_limit=spec["stop"],
            ):
                post = score_candidates(hf_model, tokenizer, case)
            conditions[name] = enrich(
                post,
                base,
                source_answer=source_answer,
                target_answer=target_answer,
            )

        record = {
            "case_id": case_id,
            "source_concept": source_concept,
            "target_concept": target_concept,
            "source_answer": source_answer,
            "target_answer": target_answer,
            "conditions": conditions,
        }
        records.append(record)
        print(json.dumps({
            "case_id": case_id,
            "target": target_answer,
            "gains": {name: round(float(v["intended_target_gain"]), 4) for name, v in conditions.items()},
        }), flush=True)

    condition_summary: dict[str, Any] = {}
    for name in records[0]["conditions"]:
        sample = [row["conditions"][name] for row in records]
        condition_summary[name] = {
            "n": 4,
            "target_specificity_hits": sum(v["target_specificity_hit"] for v in sample),
            "strong_target_switches": sum(v["strong_causal_success"] for v in sample),
            "mean_intended_target_gain": mean(v["intended_target_gain"] for v in sample),
            "mean_specificity_margin": mean(v["target_specificity_margin"] for v in sample),
        }

    primary = [row["conditions"]["primary"] for row in records]
    comparison_names = [
        "random", "raw_residual", "wrong_layer", "wrong_position",
        "reverse_sign", "absent_source",
    ]
    casewise_primary_beats = {
        name: sum(
            row["conditions"]["primary"]["intended_target_gain"]
            > row["conditions"][name]["intended_target_gain"]
            for row in records
        )
        for name in comparison_names
    }
    dose_monotonic_hits = sum(
        row["conditions"]["dose_0_5"]["intended_target_gain"]
        < row["conditions"]["primary"]["intended_target_gain"]
        < row["conditions"]["dose_2_0"]["intended_target_gain"]
        for row in records
    )

    vector = {
        "semantic_vs_random": (
            casewise_primary_beats["random"] == 4
            and condition_summary["primary"]["mean_intended_target_gain"]
            > condition_summary["random"]["mean_intended_target_gain"]
        ),
        "source_specificity_vs_absent": casewise_primary_beats["absent_source"] == 4,
        "late_vs_early_layer_localization": casewise_primary_beats["wrong_layer"] == 4,
        "prompt_span_vs_first_token_localization": casewise_primary_beats["wrong_position"] == 4,
        "sign_directionality": casewise_primary_beats["reverse_sign"] == 4,
        "jacobian_transport_vs_raw": (
            casewise_primary_beats["raw_residual"] >= 3
            and condition_summary["primary"]["mean_intended_target_gain"]
            > condition_summary["raw_residual"]["mean_intended_target_gain"]
        ),
        "dose_ordering_0_5_lt_1_lt_2": dose_monotonic_hits >= 3,
    }

    summary = {
        "experiment": "0002-r20-qwen35-4b-causal-control-battery",
        "model": DEFAULT_MODEL,
        "resolved_model_revision": resolved_revision,
        "jlens_upstream_commit": JLENS_UPSTREAM_COMMIT,
        "lens_revision": DEFAULT_LENS_REVISION,
        "lens_file": DEFAULT_LENS_FILE,
        "early_layers": early_layers,
        "late_layers": late_layers,
        "absent_source_surface": absent_surface,
        "absent_source_token_id": absent_token,
        "case_count": 4,
        "condition_summary": condition_summary,
        "casewise_primary_beats_control": casewise_primary_beats,
        "dose_monotonic_hits": dose_monotonic_hits,
        "falsification_vector": vector,
        "interpretation_rule": (
            "Each vector element is independent. A false element constrains the "
            "causal interpretation and is not averaged away by other controls."
        ),
    }
    (out_dir / "records.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
