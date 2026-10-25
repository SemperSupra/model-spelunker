#!/usr/bin/env python3
"""Experiment 0002: causal multilingual hidden-bridge writes.

Two execution modes share the same apparatus:

``paired``
    Reproduces the first eight-case EN/DE causal smoke with one predetermined
    counterfactual target per source concept.

``all-other``
    For every behavior-valid source bridge, write each of the other country
    coordinates in turn.  This is the target-address specificity test: a useful
    latent address should preferentially increase the downstream answer tied to
    the coordinate that was actually written, not merely suppress the source.

Canonical English J-space token coordinates are used unchanged in every input
language.  Only prompt positions are patched; candidate answer tokens are never
intervened on.
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
from transformers import AutoModelForCausalLM, AutoTokenizer

import jlens
from jspace_interventions import jspace_swap
from run_multilingual_bridge_cloze import candidate_logprob_scores, read_jsonl


JLENS_UPSTREAM_COMMIT = "581d398613e5602a5af361e1c34d3a92ea82ba8e"
DEFAULT_MODEL = "Qwen/Qwen3.5-0.8B"
DEFAULT_LENS_REPO = "neuronpedia/jacobian-lens"
DEFAULT_LENS_REVISION = "4f30bb8c97e696115d4a2ef359923b5005fc860c"
DEFAULT_LENS_FILE = (
    "qwen3.5-0.8b/jlens/Salesforce-wikitext/"
    "Qwen3.5-0.8B_jacobian_lens.pt"
)

PAIRED_TARGET = {
    "country-france": "country-canada",
    "country-canada": "country-france",
    "country-germany": "country-japan",
    "country-japan": "country-germany",
}
CONCEPT_IDS = tuple(PAIRED_TARGET)


def parse_layers(text: str) -> list[int]:
    layers: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(value) for value in part.split("-", 1))
            layers.extend(range(start, end + 1))
        else:
            layers.append(int(part))
    return sorted(set(layers))


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
    parser.add_argument(
        "--target-mode",
        choices=("paired", "all-other"),
        default="paired",
        help="paired reproduces R7; all-other runs the target-address matrix",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/experiment-0002-multilingual-bridge-causal",
    )
    return parser.parse_args()


def single_token_id(tokenizer, surface: str) -> int:
    ids = tokenizer(surface, add_special_tokens=False).input_ids
    if len(ids) != 1:
        raise ValueError(f"Canonical latent address must be one token: {surface!r} -> {ids}")
    return int(ids[0])


def candidate_map(scores: list[dict[str, Any]]) -> dict[str, float]:
    return {row["candidate"]: float(row["mean_logprob"]) for row in scores}


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
        "candidate_scores": scores,
        "by_candidate": candidate_map(scores),
    }


def targets_for(source_concept: str, mode: str) -> list[str]:
    if mode == "paired":
        return [PAIRED_TARGET[source_concept]]
    return [concept for concept in CONCEPT_IDS if concept != source_concept]


def enrich_result(
    result: dict[str, Any],
    baseline: dict[str, Any],
    *,
    source_answer: str,
    target_answer: str,
) -> dict[str, Any]:
    base = baseline["by_candidate"]
    post = result["by_candidate"]
    source_logit = post[source_answer]
    target_logit = post[target_answer]
    base_margin = base[target_answer] - base[source_answer]
    post_margin = target_logit - source_logit

    gains = {candidate: post[candidate] - base[candidate] for candidate in post}
    non_source_gains = {
        candidate: gain for candidate, gain in gains.items() if candidate != source_answer
    }
    ordered_gains = sorted(non_source_gains.items(), key=lambda item: item[1], reverse=True)
    best_gain_answer, best_gain = ordered_gains[0]
    target_gain = gains[target_answer]
    other_gains = [gain for candidate, gain in non_source_gains.items() if candidate != target_answer]
    next_best_gain = max(other_gains) if other_gains else float("-inf")

    result.update(
        {
            "source_mean_logprob": source_logit,
            "target_mean_logprob": target_logit,
            "target_minus_source_margin": post_margin,
            "margin_change_from_baseline": post_margin - base_margin,
            "candidate_gain_from_baseline": gains,
            "intended_target_gain": target_gain,
            "best_gained_non_source_answer": best_gain_answer,
            "best_gained_non_source_gain": best_gain,
            "target_specificity_margin": target_gain - next_best_gain,
            "target_specificity_hit": best_gain_answer == target_answer,
            "prefers_source": source_logit > target_logit,
            "prefers_target": target_logit > source_logit,
            "strong_causal_success": (
                baseline["predicted_answer"] == source_answer
                and result["predicted_answer"] == target_answer
            ),
            "preference_flip": (
                base[source_answer] > base[target_answer]
                and target_logit > source_logit
            ),
        }
    )
    # The compact records need the score list, not a duplicated lookup map.
    result.pop("by_candidate", None)
    return result


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
        raise ValueError("No cases selected for causal bridge experiment")

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

    # Force one canonical English lexicalization per concept, then reuse the
    # same token coordinate in every surface language.
    canonical_surface: dict[str, str] = {}
    canonical_token: dict[str, int] = {}
    for concept_id in CONCEPT_IDS:
        english_case = case_by_key[(concept_id, "en")]
        surface = english_case["intermediate_surfaces"][0]
        canonical_surface[concept_id] = surface
        canonical_token[concept_id] = single_token_id(tokenizer, surface)

    conditions = {
        "late_bridge": (late_layers, "coordinate_swap"),
        "early_bridge": (early_layers, "coordinate_swap"),
        "late_random": (late_layers, "random_norm_matched"),
    }

    baseline_by_case: dict[str, dict[str, Any]] = {}
    prompt_len_by_case: dict[str, int] = {}
    for case in selected:
        baseline_by_case[case["case_id"]] = score_candidates(hf_model, tokenizer, case)
        prompt_len_by_case[case["case_id"]] = len(
            tokenizer(case["prompt"], add_special_tokens=False).input_ids
        )

    records: list[dict[str, Any]] = []
    pair_count = sum(len(targets_for(case["concept_id"], args.target_mode)) for case in selected)
    print(
        f"model={args.model} revision={resolved_revision} source_cases={len(selected)} "
        f"target_pairs={pair_count} mode={args.target_mode} late={late_layers} "
        f"early={early_layers} strength={args.strength}",
        flush=True,
    )

    for case in selected:
        source_concept = case["concept_id"]
        source_answer = case["correct_answer"]
        baseline_internal = baseline_by_case[case["case_id"]]
        baseline = {
            "predicted_answer": baseline_internal["predicted_answer"],
            "candidate_scores": baseline_internal["candidate_scores"],
        }
        prompt_len = prompt_len_by_case[case["case_id"]]

        for target_concept in targets_for(source_concept, args.target_mode):
            target_case = case_by_key[(target_concept, case["language"])]
            target_answer = target_case["correct_answer"]
            row: dict[str, Any] = {
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
                "prompt_tokens": prompt_len,
                "baseline": baseline,
                "conditions": {},
            }

            for name, (layers, mode) in conditions.items():
                with jspace_swap(
                    model,
                    lens,
                    canonical_token[source_concept],
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
                result["strength"] = args.strength
                row["conditions"][name] = result

            records.append(row)
            print(
                json.dumps(
                    {
                        "case_id": row["case_id"],
                        "language": row["language"],
                        "swap": f"{source_concept}->{target_concept}",
                        "baseline": baseline["predicted_answer"],
                        "target": target_answer,
                        "late": row["conditions"]["late_bridge"]["predicted_answer"],
                        "late_specific": row["conditions"]["late_bridge"]["target_specificity_hit"],
                        "early": row["conditions"]["early_bridge"]["predicted_answer"],
                        "early_specific": row["conditions"]["early_bridge"]["target_specificity_hit"],
                        "random": row["conditions"]["late_random"]["predicted_answer"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    baseline_valid_cases = sum(
        baseline_by_case[case["case_id"]]["predicted_answer"] == case["correct_answer"]
        for case in selected
    )
    condition_summary: dict[str, Any] = {}
    for name in conditions:
        values = [row["conditions"][name] for row in records]
        condition_summary[name] = {
            "n": len(values),
            "strong_causal_successes": sum(v["strong_causal_success"] for v in values),
            "preference_flips": sum(v["preference_flip"] for v in values),
            "target_specificity_hits": sum(v["target_specificity_hit"] for v in values),
            "target_specificity_rate": mean(float(v["target_specificity_hit"]) for v in values),
            "mean_target_specificity_margin": mean(v["target_specificity_margin"] for v in values),
            "mean_intended_target_gain": mean(v["intended_target_gain"] for v in values),
            "mean_margin_change": mean(v["margin_change_from_baseline"] for v in values),
        }

    by_direction: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_direction[f"{row['source_concept']}->{row['target_concept']}"].append(row)
    transfer_summary: dict[str, Any] = {}
    for direction, direction_rows in sorted(by_direction.items()):
        late = [row["conditions"]["late_bridge"] for row in direction_rows]
        early = [row["conditions"]["early_bridge"] for row in direction_rows]
        transfer_summary[direction] = {
            "languages": sorted(row["language"] for row in direction_rows),
            "all_languages_baseline_valid": all(
                baseline_by_case[row["case_id"]]["predicted_answer"] == row["source_answer"]
                for row in direction_rows
            ),
            "late_all_languages_target_specific": all(v["target_specificity_hit"] for v in late),
            "late_all_languages_strong_causal_success": all(v["strong_causal_success"] for v in late),
            "early_all_languages_target_specific": all(v["target_specificity_hit"] for v in early),
            "early_all_languages_strong_causal_success": all(v["strong_causal_success"] for v in early),
            "mean_late_target_specificity_margin": mean(v["target_specificity_margin"] for v in late),
            "mean_late_margin_change": mean(v["margin_change_from_baseline"] for v in late),
        }

    by_source_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_source_case[row["case_id"]].append(row)
    source_specificity: dict[str, Any] = {}
    for case_id, source_rows in sorted(by_source_case.items()):
        source_specificity[case_id] = {
            "language": source_rows[0]["language"],
            "source_concept": source_rows[0]["source_concept"],
            "n_targets": len(source_rows),
            "late_target_specificity_hits": sum(
                row["conditions"]["late_bridge"]["target_specificity_hit"]
                for row in source_rows
            ),
            "early_target_specificity_hits": sum(
                row["conditions"]["early_bridge"]["target_specificity_hit"]
                for row in source_rows
            ),
            "late_strong_target_switches": sum(
                row["conditions"]["late_bridge"]["strong_causal_success"]
                for row in source_rows
            ),
            "early_strong_target_switches": sum(
                row["conditions"]["early_bridge"]["strong_causal_success"]
                for row in source_rows
            ),
        }

    summary = {
        "experiment": "0002-multilingual-hidden-bridge-causal-write",
        "target_mode": args.target_mode,
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
        "source_case_count": len(selected),
        "target_pair_count": len(records),
        "baseline_valid_source_cases": baseline_valid_cases,
        "canonical_latent_surfaces": canonical_surface,
        "conditions": condition_summary,
        "cross_language_transfer": transfer_summary,
        "source_specificity": source_specificity,
        "target_specificity_definition": (
            "intended target capital has the largest mean-logprob gain from baseline among "
            "all non-source capital candidates"
        ),
        "interpretation": (
            "Target-address calibration. A target-specific gain is stronger evidence than "
            "source suppression. Early/late bands are treated as alternate writable stages, "
            "not as a promotion criterion. Thai and downstream-function reuse remain later gates."
        ),
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
