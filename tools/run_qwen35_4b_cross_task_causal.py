#!/usr/bin/env python3
"""Experiment 0002: Qwen3.5-4B paired cross-task causal reuse smoke.

One model/lens instance is reused across two downstream functions (capital and
nationality/demonym). The same canonical English country token coordinates are
written into English and German prompts. The intervention band is selected
before outcomes as the last five fitted source layers in the pinned lens.

This is deliberately a paired smoke, not the full all-target matrix. It asks
whether a country address that changes one semantic consequence also changes a
second consequence, while a norm-matched random displacement does not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch
from huggingface_hub import hf_hub_download, model_info
from transformers import AutoModelForImageTextToText, AutoTokenizer

import jlens
from jspace_interventions import jspace_swap
from run_multilingual_bridge_cloze import candidate_logprob_scores, read_jsonl

JLENS_UPSTREAM_COMMIT = "581d398613e5602a5af361e1c34d3a92ea82ba8e"
DEFAULT_MODEL = "Qwen/Qwen3.5-4B"
DEFAULT_LENS_REPO = "neuronpedia/jacobian-lens"
DEFAULT_LENS_REVISION = "91271eb5b15a43eebed7bb447618738754f1379a"
DEFAULT_LENS_FILE = (
    "qwen3.5-4b/jlens/Salesforce-wikitext/"
    "Qwen3.5-4B_jacobian_lens_n1000.pt"
)

PAIRED_TARGET = {
    "country-france": "country-canada",
    "country-canada": "country-france",
    "country-germany": "country-japan",
    "country-japan": "country-germany",
}
CONCEPT_IDS = tuple(PAIRED_TARGET)
FUNCTION_FIXTURES = {
    "capital": "fixtures/experiment-0002/multilingual-indirect-bridge-cloze.jsonl",
    "demonym": "fixtures/experiment-0002/multilingual-indirect-bridge-demonym.jsonl",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--revision", default="main")
    p.add_argument("--lens-repo", default=DEFAULT_LENS_REPO)
    p.add_argument("--lens-revision", default=DEFAULT_LENS_REVISION)
    p.add_argument("--lens-file", default=DEFAULT_LENS_FILE)
    p.add_argument("--strength", type=float, default=1.0)
    p.add_argument("--seed", type=int, default=1729)
    p.add_argument(
        "--output-dir",
        default="artifacts/experiment-0002-qwen35-4b-cross-task-causal",
    )
    return p.parse_args()


def one_token_id(tokenizer, surface: str) -> int:
    ids = tokenizer(surface, add_special_tokens=False).input_ids
    if len(ids) != 1:
        raise ValueError(f"Canonical latent address is not one token: {surface!r} -> {ids}")
    return int(ids[0])


def score_candidates(hf_model, tokenizer, case: dict[str, Any]) -> dict[str, Any]:
    scores = candidate_logprob_scores(
        hf_model,
        tokenizer,
        case["prompt"],
        case["language"],
        case["answer_candidates"],
    )
    ordered = sorted(scores, key=lambda row: row["mean_logprob"], reverse=True)
    return {
        "predicted_answer": ordered[0]["candidate"],
        "scores": scores,
        "by_candidate": {row["candidate"]: float(row["mean_logprob"]) for row in scores},
    }


def enrich(
    post: dict[str, Any],
    baseline: dict[str, Any],
    *,
    source_answer: str,
    target_answer: str,
) -> dict[str, Any]:
    base = baseline["by_candidate"]
    after = post["by_candidate"]
    gains = {candidate: after[candidate] - base[candidate] for candidate in after}
    non_source = {candidate: gain for candidate, gain in gains.items() if candidate != source_answer}
    best_answer, best_gain = max(non_source.items(), key=lambda item: item[1])
    target_gain = gains[target_answer]
    other_gains = [gain for candidate, gain in non_source.items() if candidate != target_answer]
    next_best = max(other_gains) if other_gains else float("-inf")
    base_margin = base[target_answer] - base[source_answer]
    post_margin = after[target_answer] - after[source_answer]
    return {
        "predicted_answer": post["predicted_answer"],
        "candidate_scores": post["scores"],
        "intended_target_gain": target_gain,
        "best_gained_non_source_answer": best_answer,
        "best_gained_non_source_gain": best_gain,
        "target_specificity_hit": best_answer == target_answer,
        "target_specificity_margin": target_gain - next_best,
        "target_minus_source_margin": post_margin,
        "margin_change_from_baseline": post_margin - base_margin,
        "strong_causal_success": (
            baseline["predicted_answer"] == source_answer
            and post["predicted_answer"] == target_answer
        ),
        "preference_flip": (
            base[source_answer] > base[target_answer]
            and after[target_answer] > after[source_answer]
        ),
    }


def main() -> int:
    args = parse_args()
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

    functions: dict[str, list[dict[str, Any]]] = {}
    case_maps: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for function_name, fixture in FUNCTION_FIXTURES.items():
        rows = [
            row for row in read_jsonl(Path(fixture))
            if row["language"] in {"en", "de"} and row["concept_id"] in CONCEPT_IDS
        ]
        if len(rows) != 8:
            raise ValueError(f"Expected 8 {function_name} EN/DE rows, got {len(rows)}")
        functions[function_name] = rows
        case_maps[function_name] = {
            (row["concept_id"], row["language"]): row for row in rows
        }

    # Canonical addresses come from the English capital fixture and are reused
    # unchanged in German and in the demonym function.
    capital_map = case_maps["capital"]
    canonical_surface: dict[str, str] = {}
    canonical_token: dict[str, int] = {}
    for concept_id in CONCEPT_IDS:
        surface = capital_map[(concept_id, "en")]["intermediate_surfaces"][0]
        canonical_surface[concept_id] = surface
        canonical_token[concept_id] = one_token_id(tokenizer, surface)

    baseline: dict[tuple[str, str], dict[str, Any]] = {}
    prompt_lengths: dict[tuple[str, str], int] = {}
    for function_name, rows in functions.items():
        for case in rows:
            key = (function_name, case["case_id"])
            scored = score_candidates(hf_model, tokenizer, case)
            baseline[key] = scored
            prompt_lengths[key] = len(
                tokenizer(case["prompt"], add_special_tokens=False).input_ids
            )
            if scored["predicted_answer"] != case["correct_answer"]:
                raise RuntimeError(
                    f"Behavior gate regressed inside causal run: {function_name} "
                    f"{case['case_id']} predicted {scored['predicted_answer']!r} "
                    f"expected {case['correct_answer']!r}"
                )

    records: list[dict[str, Any]] = []
    for function_name, rows in functions.items():
        cmap = case_maps[function_name]
        for case in rows:
            source_concept = case["concept_id"]
            target_concept = PAIRED_TARGET[source_concept]
            target_case = cmap[(target_concept, case["language"])]
            source_answer = case["correct_answer"]
            target_answer = target_case["correct_answer"]
            key = (function_name, case["case_id"])
            base = baseline[key]
            prompt_len = prompt_lengths[key]

            row: dict[str, Any] = {
                "function": function_name,
                "case_id": case["case_id"],
                "language": case["language"],
                "prompt_sha256": hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest(),
                "source_concept": source_concept,
                "target_concept": target_concept,
                "source_latent_surface": canonical_surface[source_concept],
                "target_latent_surface": canonical_surface[target_concept],
                "source_latent_token_id": canonical_token[source_concept],
                "target_latent_token_id": canonical_token[target_concept],
                "source_answer": source_answer,
                "target_answer": target_answer,
                "baseline_predicted_answer": base["predicted_answer"],
                "conditions": {},
            }

            for condition, mode in (
                ("jspace", "coordinate_swap"),
                ("random", "random_norm_matched"),
            ):
                with jspace_swap(
                    model,
                    lens,
                    canonical_token[source_concept],
                    canonical_token[target_concept],
                    intervention_layers,
                    strength=args.strength,
                    mode=mode,
                    seed=args.seed,
                    key=f"{function_name}|{case['case_id']}|{target_concept}|{condition}",
                    position_limit=prompt_len,
                ):
                    post = score_candidates(hf_model, tokenizer, case)
                row["conditions"][condition] = enrich(
                    post,
                    base,
                    source_answer=source_answer,
                    target_answer=target_answer,
                )

            records.append(row)
            print(
                json.dumps(
                    {
                        "function": function_name,
                        "case_id": case["case_id"],
                        "language": case["language"],
                        "swap": f"{source_concept}->{target_concept}",
                        "target": target_answer,
                        "jspace_target_gain": row["conditions"]["jspace"]["intended_target_gain"],
                        "jspace_specific": row["conditions"]["jspace"]["target_specificity_hit"],
                        "jspace_strong": row["conditions"]["jspace"]["strong_causal_success"],
                        "random_target_gain": row["conditions"]["random"]["intended_target_gain"],
                        "random_specific": row["conditions"]["random"]["target_specificity_hit"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    function_summary: dict[str, Any] = {}
    for function_name in FUNCTION_FIXTURES:
        rows = [row for row in records if row["function"] == function_name]
        j = [row["conditions"]["jspace"] for row in rows]
        r = [row["conditions"]["random"] for row in rows]
        pairwise_beats_random = sum(
            a["intended_target_gain"] > b["intended_target_gain"]
            for a, b in zip(j, r)
        )
        function_summary[function_name] = {
            "n": len(rows),
            "jspace_target_specificity_hits": sum(v["target_specificity_hit"] for v in j),
            "jspace_strong_switches": sum(v["strong_causal_success"] for v in j),
            "jspace_preference_flips": sum(v["preference_flip"] for v in j),
            "jspace_mean_target_gain": mean(v["intended_target_gain"] for v in j),
            "jspace_mean_specificity_margin": mean(v["target_specificity_margin"] for v in j),
            "random_target_specificity_hits": sum(v["target_specificity_hit"] for v in r),
            "random_strong_switches": sum(v["strong_causal_success"] for v in r),
            "random_mean_target_gain": mean(v["intended_target_gain"] for v in r),
            "jspace_target_gain_beats_random_cases": pairwise_beats_random,
        }

    by_direction: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        direction = f"{row['source_concept']}->{row['target_concept']}"
        by_direction[direction].append(row)
    reusable_directions: dict[str, Any] = {}
    for direction, rows in sorted(by_direction.items()):
        # 4 rows per direction when fully represented: EN/DE x 2 functions.
        reusable_directions[direction] = {
            "n": len(rows),
            "functions": sorted({row["function"] for row in rows}),
            "languages": sorted({row["language"] for row in rows}),
            "all_cross_task_rows_jspace_specific": all(
                row["conditions"]["jspace"]["target_specificity_hit"] for row in rows
            ),
            "all_cross_task_rows_jspace_gain_beats_random": all(
                row["conditions"]["jspace"]["intended_target_gain"]
                > row["conditions"]["random"]["intended_target_gain"]
                for row in rows
            ),
            "jspace_strong_switches": sum(
                row["conditions"]["jspace"]["strong_causal_success"] for row in rows
            ),
        }

    promotion_pass = all(
        s["jspace_target_specificity_hits"] >= 6
        and s["jspace_target_gain_beats_random_cases"] >= 6
        and s["jspace_mean_target_gain"] > 0
        and s["jspace_mean_target_gain"] > s["random_mean_target_gain"]
        and s["random_strong_switches"] == 0
        for s in function_summary.values()
    ) and any(
        row["n"] == 4
        and row["all_cross_task_rows_jspace_specific"]
        and row["all_cross_task_rows_jspace_gain_beats_random"]
        for row in reusable_directions.values()
    )

    summary = {
        "experiment": "0002-qwen35-4b-cross-task-causal-reuse",
        "model": args.model,
        "resolved_model_revision": resolved_revision,
        "model_class": hf_model.__class__.__name__,
        "jlens_upstream_commit": JLENS_UPSTREAM_COMMIT,
        "lens_repo": args.lens_repo,
        "lens_revision": args.lens_revision,
        "lens_file": args.lens_file,
        "lens_n_prompts": lens.n_prompts,
        "lens_d_model": lens.d_model,
        "lens_source_layers": fitted_layers,
        "intervention_layers": intervention_layers,
        "intervention_layer_rule": "last five fitted J-lens source layers, precommitted before outcomes",
        "strength": args.strength,
        "canonical_latent_surfaces": canonical_surface,
        "baseline_valid_cases": 16,
        "record_count": len(records),
        "function_summary": function_summary,
        "reusable_directions": reusable_directions,
        "promotion_rule": {
            "per_function": (
                ">=6/8 J-space target-specific; >=6/8 J-space intended-target gain beats matched random; "
                "positive mean J-space target gain greater than random; random strong switches = 0"
            ),
            "cross_task_direction": (
                ">=1 fixed source->target direction is J-space target-specific and beats random in all "
                "four EN/DE x capital/demonym rows"
            ),
        },
        "promotion_pass": promotion_pass,
        "interpretation": (
            "Paired cross-task causal reuse smoke. A pass supports reusable addressability of the "
            "country coordinate across two downstream semantic functions, but does not establish "
            "universality, composition, or language-independent ontology."
        ),
    }

    (out_dir / "records.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
