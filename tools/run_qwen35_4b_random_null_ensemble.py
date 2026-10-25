#!/usr/bin/env python3
"""Experiment 0002 R17: empirical matched-random null calibration.

R16 remains a strict non-pass because one deterministic norm-matched random
control caused a strong capital-answer switch. This follow-up does not reroll
R16 or change its promotion rule. It freezes the R16 J-space outcomes and asks
how often independent norm-matched random directions produce comparable target
gains on the same eight capital cases.

The original seed 1729 is included as a reproducibility check. Three additional
seeds are fixed before execution. Model, prompts, concepts, latent addresses,
layer band, intervention strength, scoring, and random-control construction are
unchanged from R16.
"""

from __future__ import annotations

import argparse
import hashlib
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
REFERENCE_FIXTURE = "fixtures/experiment-0002/qwen35-4b-r16-capital-reference.jsonl"
DEFAULT_SEEDS = (1729, 2718, 31415, 424242)
REFERENCE_GAIN_TOLERANCE = 0.05


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--revision", default="main")
    p.add_argument("--lens-repo", default=DEFAULT_LENS_REPO)
    p.add_argument("--lens-revision", default=DEFAULT_LENS_REVISION)
    p.add_argument("--lens-file", default=DEFAULT_LENS_FILE)
    p.add_argument("--strength", type=float, default=1.0)
    p.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    p.add_argument("--reference", default=REFERENCE_FIXTURE)
    p.add_argument(
        "--output-dir",
        default="artifacts/experiment-0002-qwen35-4b-random-null-ensemble",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    seeds = [int(seed) for seed in args.seeds]
    if seeds != list(DEFAULT_SEEDS):
        raise ValueError(
            f"R17 seeds are precommitted as {list(DEFAULT_SEEDS)}; got {seeds}"
        )

    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    reference_rows = read_jsonl(Path(args.reference))
    reference = {row["case_id"]: row for row in reference_rows}
    if len(reference) != 8:
        raise ValueError(f"Expected 8 frozen R16 capital rows, got {len(reference)}")

    rows = [
        row
        for row in read_jsonl(Path(CAPITAL_FIXTURE))
        if row["language"] in {"en", "de"} and row["concept_id"] in CONCEPT_IDS
    ]
    if len(rows) != 8:
        raise ValueError(f"Expected 8 capital EN/DE rows, got {len(rows)}")

    # Freeze identity/provenance before loading the expensive model.
    for case in rows:
        ref = reference.get(case["case_id"])
        if ref is None:
            raise ValueError(f"Missing frozen reference for {case['case_id']}")
        prompt_sha = hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest()
        expected = {
            "language": case["language"],
            "prompt_sha256": prompt_sha,
            "source_concept": case["concept_id"],
            "target_concept": PAIRED_TARGET[case["concept_id"]],
            "source_answer": case["correct_answer"],
        }
        for field, value in expected.items():
            if ref[field] != value:
                raise ValueError(
                    f"Frozen R16 reference drift for {case['case_id']} {field}: "
                    f"{ref[field]!r} != {value!r}"
                )

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(f"Could not resolve immutable revision for {args.model}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    hf_model = AutoModelForImageTextToText.from_pretrained(
        args.model,
        revision=resolved_revision,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
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
    fitted_layers = sorted(int(layer) for layer in lens.source_layers)
    intervention_layers = fitted_layers[-5:]

    by_concept_language = {(row["concept_id"], row["language"]): row for row in rows}
    canonical_surface: dict[str, str] = {}
    canonical_token: dict[str, int] = {}
    for concept_id in CONCEPT_IDS:
        surface = by_concept_language[(concept_id, "en")]["intermediate_surfaces"][0]
        canonical_surface[concept_id] = surface
        canonical_token[concept_id] = one_token_id(tokenizer, surface)

    baselines: dict[str, dict[str, Any]] = {}
    prompt_lengths: dict[str, int] = {}
    for case in rows:
        scored = score_candidates(hf_model, tokenizer, case)
        baselines[case["case_id"]] = scored
        prompt_lengths[case["case_id"]] = len(
            tokenizer(case["prompt"], add_special_tokens=False).input_ids
        )
        if scored["predicted_answer"] != case["correct_answer"]:
            raise RuntimeError(
                f"Behavior gate regressed: {case['case_id']} predicted "
                f"{scored['predicted_answer']!r}; expected {case['correct_answer']!r}"
            )

    records: list[dict[str, Any]] = []
    for case in rows:
        case_id = case["case_id"]
        source_concept = case["concept_id"]
        target_concept = PAIRED_TARGET[source_concept]
        target_case = by_concept_language[(target_concept, case["language"])]
        source_answer = case["correct_answer"]
        target_answer = target_case["correct_answer"]
        base = baselines[case_id]
        ref = reference[case_id]

        seed_results: list[dict[str, Any]] = []
        for seed in seeds:
            with jspace_swap(
                model,
                lens,
                canonical_token[source_concept],
                canonical_token[target_concept],
                intervention_layers,
                strength=args.strength,
                mode="random_norm_matched",
                seed=seed,
                # Keep the exact R16 key; vary seed only.
                key=f"capital|{case_id}|{target_concept}|random",
                position_limit=prompt_lengths[case_id],
            ):
                post = score_candidates(hf_model, tokenizer, case)
            result = enrich(
                post,
                base,
                source_answer=source_answer,
                target_answer=target_answer,
            )
            result["seed"] = seed
            seed_results.append(result)
            print(
                json.dumps(
                    {
                        "case_id": case_id,
                        "language": case["language"],
                        "seed": seed,
                        "target": target_answer,
                        "random_target_gain": result["intended_target_gain"],
                        "random_specific": result["target_specificity_hit"],
                        "random_strong": result["strong_causal_success"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

        seed1729 = next(result for result in seed_results if result["seed"] == 1729)
        r16_reproduced = (
            abs(
                seed1729["intended_target_gain"]
                - float(ref["r16_random_intended_target_gain"])
            )
            <= REFERENCE_GAIN_TOLERANCE
            and bool(seed1729["target_specificity_hit"])
            == bool(ref["r16_random_target_specificity_hit"])
            and bool(seed1729["strong_causal_success"])
            == bool(ref["r16_random_strong_causal_success"])
        )
        max_random_gain = max(float(result["intended_target_gain"]) for result in seed_results)
        records.append(
            {
                "case_id": case_id,
                "language": case["language"],
                "prompt_sha256": ref["prompt_sha256"],
                "source_concept": source_concept,
                "target_concept": target_concept,
                "source_answer": source_answer,
                "target_answer": target_answer,
                "jspace_intended_target_gain_r16": float(ref["jspace_intended_target_gain"]),
                "r16_seed1729_reproduced": r16_reproduced,
                "max_random_intended_target_gain": max_random_gain,
                "jspace_gain_exceeds_max_random": (
                    float(ref["jspace_intended_target_gain"]) > max_random_gain
                ),
                "random_results": seed_results,
            }
        )

    seed_summary: dict[str, Any] = {}
    for seed in seeds:
        sample = [
            next(result for result in row["random_results"] if result["seed"] == seed)
            for row in records
        ]
        seed_summary[str(seed)] = {
            "n": len(sample),
            "target_specificity_hits": sum(v["target_specificity_hit"] for v in sample),
            "strong_target_switches": sum(v["strong_causal_success"] for v in sample),
            "mean_intended_target_gain": mean(v["intended_target_gain"] for v in sample),
            "max_intended_target_gain": max(v["intended_target_gain"] for v in sample),
        }

    jspace_mean_gain = mean(
        float(reference[row["case_id"]]["jspace_intended_target_gain"]) for row in records
    )
    max_seed_mean_random = max(
        float(row["mean_intended_target_gain"]) for row in seed_summary.values()
    )
    seed1729_reproduction_pass = all(row["r16_seed1729_reproduced"] for row in records)
    casewise_max_separation_hits = sum(
        row["jspace_gain_exceeds_max_random"] for row in records
    )

    # This gate does NOT retroactively promote R16. It only determines whether
    # a four-seed empirical-null control is sufficiently stable to use in the
    # next held-out/context-invariance causal rep.
    null_calibration_pass = (
        seed1729_reproduction_pass
        and casewise_max_separation_hits == 8
        and jspace_mean_gain > max_seed_mean_random
    )

    summary = {
        "experiment": "0002-r17-qwen35-4b-random-null-ensemble",
        "purpose": "calibrate empirical matched-random null after R16 strict non-pass",
        "r16_remains_non_pass": True,
        "model": args.model,
        "resolved_model_revision": resolved_revision,
        "model_class": hf_model.__class__.__name__,
        "jlens_upstream_commit": JLENS_UPSTREAM_COMMIT,
        "lens_repo": args.lens_repo,
        "lens_revision": args.lens_revision,
        "lens_file": args.lens_file,
        "lens_n_prompts": lens.n_prompts,
        "lens_source_layers": fitted_layers,
        "intervention_layers": intervention_layers,
        "intervention_layer_rule": "same last five fitted J-lens source layers as R16",
        "strength": args.strength,
        "seeds": seeds,
        "seed1729_reference_gain_tolerance": REFERENCE_GAIN_TOLERANCE,
        "case_count": len(records),
        "random_intervention_count": len(records) * len(seeds),
        "seed1729_reproduction_pass": seed1729_reproduction_pass,
        "casewise_jspace_gain_exceeds_max_random": casewise_max_separation_hits,
        "jspace_mean_target_gain_r16": jspace_mean_gain,
        "max_seed_mean_random_target_gain": max_seed_mean_random,
        "seed_summary": seed_summary,
        "null_calibration_rule": (
            "R16 seed 1729 reproduces on all 8 cases; frozen R16 J-space intended-target "
            "gain exceeds the maximum of 4 matched-random seeds on all 8 cases; frozen "
            "R16 mean J-space gain exceeds every seed-level random mean. This does not "
            "retroactively change R16's strict promotion failure."
        ),
        "null_calibration_pass": null_calibration_pass,
        "next_if_pass": (
            "precommit a held-out context/paraphrase causal replication using a multi-seed "
            "empirical-null control rather than a single zero-hit random draw"
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
