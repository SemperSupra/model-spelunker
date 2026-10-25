#!/usr/bin/env python3
"""Experiment 0002 R18: held-out context invariance of writable country addresses.

The country addresses, model, lens, layer band, intervention strength, semantic
source->target pairs, and scoring rules are frozen from R16/R17. Only the prompt
context changes. The first R18 slice uses a held-out capital/travel formulation
in English and German.

A three-seed norm-matched random ensemble is used as the empirical null. This is
not a reroll of R16 and does not retroactively alter R16's strict non-pass.
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

DEFAULT_FIXTURE = (
    "fixtures/experiment-0002/"
    "multilingual-indirect-bridge-capital-context-holdout.jsonl"
)
CANONICAL_ADDRESS_FIXTURE = (
    "fixtures/experiment-0002/multilingual-indirect-bridge-cloze.jsonl"
)
DEFAULT_SEEDS = (1729, 2718, 31415)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", default=DEFAULT_FIXTURE)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--revision", default="main")
    p.add_argument("--lens-repo", default=DEFAULT_LENS_REPO)
    p.add_argument("--lens-revision", default=DEFAULT_LENS_REVISION)
    p.add_argument("--lens-file", default=DEFAULT_LENS_FILE)
    p.add_argument("--strength", type=float, default=1.0)
    p.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    p.add_argument(
        "--output-dir",
        default="artifacts/experiment-0002-qwen35-4b-context-invariance",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    seeds = [int(seed) for seed in args.seeds]
    if seeds != list(DEFAULT_SEEDS):
        raise ValueError(
            f"R18 seeds are precommitted as {list(DEFAULT_SEEDS)}; got {seeds}"
        )

    rows = [
        row
        for row in read_jsonl(Path(args.fixture))
        if row["language"] in {"en", "de"} and row["concept_id"] in CONCEPT_IDS
    ]
    if len(rows) != 8:
        raise ValueError(f"Expected 8 held-out EN/DE rows, got {len(rows)}")
    heldout = {(row["concept_id"], row["language"]): row for row in rows}
    if len(heldout) != 8:
        raise ValueError("Held-out fixture must contain each concept-language pair once")

    canonical_rows = [
        row
        for row in read_jsonl(Path(CANONICAL_ADDRESS_FIXTURE))
        if row["language"] == "en" and row["concept_id"] in CONCEPT_IDS
    ]
    canonical_by_concept = {row["concept_id"]: row for row in canonical_rows}
    if len(canonical_by_concept) != 4:
        raise ValueError("Canonical address fixture must contain four English concepts")

    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

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
    if len(fitted_layers) < 5:
        raise ValueError(f"Need at least five fitted layers; found {fitted_layers}")
    intervention_layers = fitted_layers[-5:]

    canonical_surface: dict[str, str] = {}
    canonical_token: dict[str, int] = {}
    for concept_id in CONCEPT_IDS:
        surface = canonical_by_concept[concept_id]["intermediate_surfaces"][0]
        canonical_surface[concept_id] = surface
        canonical_token[concept_id] = one_token_id(tokenizer, surface)

    baselines: dict[str, dict[str, Any]] = {}
    prompt_lengths: dict[str, int] = {}
    baseline_failures: list[dict[str, str]] = []
    for case in rows:
        scored = score_candidates(hf_model, tokenizer, case)
        baselines[case["case_id"]] = scored
        prompt_lengths[case["case_id"]] = len(
            tokenizer(case["prompt"], add_special_tokens=False).input_ids
        )
        if scored["predicted_answer"] != case["correct_answer"]:
            baseline_failures.append(
                {
                    "case_id": case["case_id"],
                    "predicted": scored["predicted_answer"],
                    "expected": case["correct_answer"],
                }
            )

    # Do not spend intervention compute on a context the model cannot solve cleanly.
    if baseline_failures:
        summary = {
            "experiment": "0002-r18-qwen35-4b-context-invariance",
            "model": args.model,
            "resolved_model_revision": resolved_revision,
            "fixture": args.fixture,
            "baseline_valid_cases": 8 - len(baseline_failures),
            "baseline_failures": baseline_failures,
            "causal_executed": False,
            "context_invariance_pass": False,
            "decision": "behavior gate failed; causal interventions skipped",
        }
        (out_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
        return 0

    records: list[dict[str, Any]] = []
    for case in rows:
        case_id = case["case_id"]
        source_concept = case["concept_id"]
        target_concept = PAIRED_TARGET[source_concept]
        target_case = heldout[(target_concept, case["language"])]
        source_answer = case["correct_answer"]
        target_answer = target_case["correct_answer"]
        base = baselines[case_id]
        position_limit = prompt_lengths[case_id]

        with jspace_swap(
            model,
            lens,
            canonical_token[source_concept],
            canonical_token[target_concept],
            intervention_layers,
            strength=args.strength,
            mode="coordinate_swap",
            key=f"r18|{case_id}|{target_concept}|jspace",
            position_limit=position_limit,
        ):
            jspace_post = score_candidates(hf_model, tokenizer, case)
        jspace_result = enrich(
            jspace_post,
            base,
            source_answer=source_answer,
            target_answer=target_answer,
        )

        random_results: list[dict[str, Any]] = []
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
                key=f"r18|{case_id}|{target_concept}|random",
                position_limit=position_limit,
            ):
                random_post = score_candidates(hf_model, tokenizer, case)
            result = enrich(
                random_post,
                base,
                source_answer=source_answer,
                target_answer=target_answer,
            )
            result["seed"] = seed
            random_results.append(result)

        max_random_gain = max(
            float(result["intended_target_gain"]) for result in random_results
        )
        record = {
            "case_id": case_id,
            "language": case["language"],
            "source_concept": source_concept,
            "target_concept": target_concept,
            "source_latent_surface": canonical_surface[source_concept],
            "target_latent_surface": canonical_surface[target_concept],
            "source_answer": source_answer,
            "target_answer": target_answer,
            "baseline_predicted_answer": base["predicted_answer"],
            "jspace": jspace_result,
            "random_results": random_results,
            "max_random_intended_target_gain": max_random_gain,
            "jspace_gain_exceeds_max_random": (
                float(jspace_result["intended_target_gain"]) > max_random_gain
            ),
        }
        records.append(record)
        print(
            json.dumps(
                {
                    "case_id": case_id,
                    "language": case["language"],
                    "swap": f"{source_concept}->{target_concept}",
                    "target": target_answer,
                    "jspace_target_gain": jspace_result["intended_target_gain"],
                    "jspace_specific": jspace_result["target_specificity_hit"],
                    "jspace_strong": jspace_result["strong_causal_success"],
                    "max_random_target_gain": max_random_gain,
                    "jspace_beats_max_random": record["jspace_gain_exceeds_max_random"],
                },
                ensure_ascii=False,
            ),
            flush=True,
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
        }

    jspace_specific_hits = sum(
        row["jspace"]["target_specificity_hit"] for row in records
    )
    jspace_strong_switches = sum(
        row["jspace"]["strong_causal_success"] for row in records
    )
    casewise_max_separation_hits = sum(
        row["jspace_gain_exceeds_max_random"] for row in records
    )
    jspace_mean_gain = mean(
        row["jspace"]["intended_target_gain"] for row in records
    )
    max_seed_mean_random = max(
        float(row["mean_intended_target_gain"]) for row in seed_summary.values()
    )

    # Precommitted R18 gate: all held-out baselines correct; target specificity
    # and empirical-null separation must hold casewise in all eight EN/DE rows.
    # Strong answer switching is reported but is not required because R16 already
    # established that target-specific causal movement need not cross every
    # decision boundary at strength 1.0.
    context_invariance_pass = (
        jspace_specific_hits == 8
        and casewise_max_separation_hits == 8
        and jspace_mean_gain > max_seed_mean_random
    )

    summary = {
        "experiment": "0002-r18-qwen35-4b-context-invariance",
        "purpose": "held-out prompt-context replication with frozen latent addresses",
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
        "intervention_layer_rule": "same last five fitted J-lens source layers as R16/R17",
        "strength": args.strength,
        "seeds": seeds,
        "fixture": args.fixture,
        "baseline_valid_cases": 8,
        "causal_executed": True,
        "case_count": len(records),
        "jspace_target_specificity_hits": jspace_specific_hits,
        "jspace_strong_switches": jspace_strong_switches,
        "casewise_jspace_gain_exceeds_max_random": casewise_max_separation_hits,
        "jspace_mean_target_gain": jspace_mean_gain,
        "max_seed_mean_random_target_gain": max_seed_mean_random,
        "seed_summary": seed_summary,
        "context_invariance_rule": (
            "8/8 held-out baselines correct; J-space target-specific on 8/8; "
            "J-space intended-target gain exceeds the maximum of 3 matched-random "
            "seeds on 8/8; mean J-space gain exceeds every seed-level random mean."
        ),
        "context_invariance_pass": context_invariance_pass,
        "next_if_pass": (
            "repeat the same frozen-address held-out-context test on the demonym function"
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
