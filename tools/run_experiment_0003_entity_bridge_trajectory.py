#!/usr/bin/env python3
"""Experiment 0003 R01: entity-bridge latent trajectory MVP.

Use the validated Qwen3.5-4B country addresses from Experiment 0002, but change
the causal question from full-prompt steering to time-local mediation.

For four English two-hop geography tasks:
1. read the hidden country at the position immediately before it would be
   emitted in a step-by-step prefix;
2. verify direct-answer and explicit-intermediate baselines;
3. patch only the explicit intermediate-country token state;
4. compare with a norm-matched random patch at the same time and the same
   semantic patch at a wrong time;
5. retain the established full-prompt direct patch as a reference condition.

This is a first trajectory slice, not a continuous-CoT experiment.
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
from run_multilingual_bridge_cloze import (
    FIT_POSITION_FLOOR,
    read_jsonl,
    resolve_single_token_surfaces,
    score_concept,
)
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

TRAJECTORY_FIXTURE = "fixtures/experiment-0003/entity-bridge-explicit-cot.jsonl"
DIRECT_FIXTURE = "fixtures/experiment-0002/multilingual-indirect-bridge-cloze.jsonl"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", default="artifacts/experiment-0003-r01-entity-bridge-trajectory")
    return p.parse_args()


def as_case(row: dict[str, Any], prompt_key: str) -> dict[str, Any]:
    return {
        "case_id": row["case_id"],
        "concept_id": row["concept_id"],
        "language": row["language"],
        "prompt": row[prompt_key],
        "correct_answer": row["correct_answer"],
        "answer_candidates": row["answer_candidates"],
    }


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
    late_layers = fitted_layers[-5:]

    trajectory_rows = read_jsonl(Path(TRAJECTORY_FIXTURE))
    if len(trajectory_rows) != 4:
        raise ValueError(f"Expected four trajectory rows, got {len(trajectory_rows)}")
    trajectory_by_concept = {row["concept_id"]: row for row in trajectory_rows}
    if set(trajectory_by_concept) != set(CONCEPT_IDS):
        raise ValueError("Trajectory fixture must cover the four frozen country concepts")

    direct_rows = [
        row for row in read_jsonl(Path(DIRECT_FIXTURE))
        if row["language"] == "en" and row["concept_id"] in CONCEPT_IDS
    ]
    direct_by_concept = {row["concept_id"]: row for row in direct_rows}
    if len(direct_by_concept) != 4:
        raise ValueError("Direct fixture must expose four English country cases")

    canonical_token: dict[str, int] = {}
    for concept_id, row in direct_by_concept.items():
        canonical_token[concept_id] = one_token_id(tokenizer, row["intermediate_surfaces"][0])

    records: list[dict[str, Any]] = []
    for row in trajectory_rows:
        source_concept = row["concept_id"]
        target_concept = PAIRED_TARGET[source_concept]
        source_id = canonical_token[source_concept]
        target_id = canonical_token[target_concept]
        target_answer = trajectory_by_concept[target_concept]["correct_answer"]

        direct_case = direct_by_concept[source_concept]
        explicit_case = as_case(row, "explicit_prompt")
        direct_base = score_candidates(hf_model, tokenizer, direct_case)
        explicit_base = score_candidates(hf_model, tokenizer, explicit_case)
        if direct_base["predicted_answer"] != direct_case["correct_answer"]:
            raise RuntimeError(f"Direct behavior gate failed: {direct_case['case_id']}")
        if explicit_base["predicted_answer"] != row["correct_answer"]:
            raise RuntimeError(f"Explicit-CoT behavior gate failed: {row['case_id']}")

        # Read the known intermediate country immediately before the country
        # token would be emitted in the reasoning prefix.
        prefix = row["pre_intermediate_prompt"]
        prefix_ids = model.encode(prefix)
        seq_len = int(prefix_ids.shape[-1])
        position = seq_len - 1
        if position < FIT_POSITION_FLOOR:
            raise ValueError(f"Pre-intermediate prefix too short for fitted lens: {row['case_id']}")
        lexicalizations = resolve_single_token_surfaces(tokenizer, [row["intermediate_surface"]])
        if len(lexicalizations) != 1:
            raise ValueError(f"Intermediate is not a unique one-token address: {row['case_id']}")
        jlens_logits, _, _ = lens.apply(model, prefix, positions=[position])
        pre_readout = score_concept(jlens_logits, lexicalizations, [position])
        del jlens_logits

        explicit_ids = tokenizer(row["explicit_prompt"], add_special_tokens=False).input_ids
        source_positions = [i for i, token_id in enumerate(explicit_ids) if int(token_id) == source_id]
        if len(source_positions) != 1:
            raise ValueError(
                f"Expected one explicit intermediate token in {row['case_id']}, got {source_positions}"
            )
        intermediate_pos = source_positions[0]
        explicit_len = len(explicit_ids)
        direct_len = len(tokenizer(direct_case["prompt"], add_special_tokens=False).input_ids)

        def run_patch(case, base, *, mode, start, stop, key, random_seed=1729):
            with jspace_swap(
                model,
                lens,
                source_id,
                target_id,
                late_layers,
                strength=1.0,
                mode=mode,
                seed=random_seed,
                key=key,
                position_start=start,
                position_limit=stop,
            ):
                post = score_candidates(hf_model, tokenizer, case)
            return enrich(
                post,
                base,
                source_answer=row["correct_answer"],
                target_answer=target_answer,
            )

        explicit_local = run_patch(
            explicit_case, explicit_base,
            mode="coordinate_swap",
            start=intermediate_pos,
            stop=intermediate_pos + 1,
            key=f"r01|{row['case_id']}|local",
        )
        explicit_random = run_patch(
            explicit_case, explicit_base,
            mode="random_norm_matched",
            start=intermediate_pos,
            stop=intermediate_pos + 1,
            key=f"r01|{row['case_id']}|random",
        )
        explicit_wrong_time = run_patch(
            explicit_case, explicit_base,
            mode="coordinate_swap",
            start=0,
            stop=1,
            key=f"r01|{row['case_id']}|wrong-time",
        )
        direct_reference = run_patch(
            direct_case, direct_base,
            mode="coordinate_swap",
            start=0,
            stop=direct_len,
            key=f"r01|{row['case_id']}|direct-reference",
        )

        record = {
            "case_id": row["case_id"],
            "source_concept": source_concept,
            "target_concept": target_concept,
            "target_answer": target_answer,
            "pre_intermediate_readout": pre_readout,
            "explicit_intermediate_position": intermediate_pos,
            "explicit_prompt_tokens": explicit_len,
            "conditions": {
                "explicit_time_local": explicit_local,
                "explicit_random_same_time": explicit_random,
                "explicit_wrong_time": explicit_wrong_time,
                "direct_full_prompt_reference": direct_reference,
            },
        }
        records.append(record)
        print(json.dumps({
            "case_id": row["case_id"],
            "pre_rank": pre_readout["best_rank"],
            "local_gain": explicit_local["intended_target_gain"],
            "random_gain": explicit_random["intended_target_gain"],
            "wrong_time_gain": explicit_wrong_time["intended_target_gain"],
            "direct_gain": direct_reference["intended_target_gain"],
        }), flush=True)

    pre_top20 = sum(row["pre_intermediate_readout"]["best_rank"] <= 20 for row in records)
    local_specific = sum(
        row["conditions"]["explicit_time_local"]["target_specificity_hit"] for row in records
    )
    local_beats_random = sum(
        row["conditions"]["explicit_time_local"]["intended_target_gain"]
        > row["conditions"]["explicit_random_same_time"]["intended_target_gain"]
        for row in records
    )
    local_beats_wrong_time = sum(
        row["conditions"]["explicit_time_local"]["intended_target_gain"]
        > row["conditions"]["explicit_wrong_time"]["intended_target_gain"]
        for row in records
    )
    direct_specific = sum(
        row["conditions"]["direct_full_prompt_reference"]["target_specificity_hit"]
        for row in records
    )
    local_mean = mean(
        row["conditions"]["explicit_time_local"]["intended_target_gain"] for row in records
    )
    random_mean = mean(
        row["conditions"]["explicit_random_same_time"]["intended_target_gain"] for row in records
    )
    wrong_time_mean = mean(
        row["conditions"]["explicit_wrong_time"]["intended_target_gain"] for row in records
    )

    trajectory_pass = (
        pre_top20 == 4
        and local_specific >= 3
        and local_beats_random == 4
        and local_beats_wrong_time == 4
        and local_mean > random_mean
        and local_mean > wrong_time_mean
        and direct_specific == 4
    )
    summary = {
        "experiment": "0003-r01-entity-bridge-latent-trajectory-mvp",
        "model": DEFAULT_MODEL,
        "resolved_model_revision": resolved_revision,
        "jlens_upstream_commit": JLENS_UPSTREAM_COMMIT,
        "lens_revision": DEFAULT_LENS_REVISION,
        "lens_file": DEFAULT_LENS_FILE,
        "intervention_layers": late_layers,
        "case_count": 4,
        "pre_intermediate_top20": pre_top20,
        "explicit_time_local_target_specificity_hits": local_specific,
        "explicit_local_beats_random_cases": local_beats_random,
        "explicit_local_beats_wrong_time_cases": local_beats_wrong_time,
        "direct_reference_target_specificity_hits": direct_specific,
        "explicit_local_mean_target_gain": local_mean,
        "explicit_random_mean_target_gain": random_mean,
        "explicit_wrong_time_mean_target_gain": wrong_time_mean,
        "trajectory_mvp_rule": (
            "4/4 pre-intermediate J-lens readout top-20; time-local semantic patch "
            "target-specific on >=3/4; local gain beats same-time random and wrong-time "
            "semantic patch on 4/4; local mean exceeds both controls; direct reference "
            "remains target-specific on 4/4."
        ),
        "trajectory_mvp_pass": trajectory_pass,
        "interpretation": (
            "A pass is evidence for time-local causal mediation of a known intermediate "
            "state. It is not evidence for continuous latent CoT or a universal operator grammar."
        ),
    }
    (out_dir / "records.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8"
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
