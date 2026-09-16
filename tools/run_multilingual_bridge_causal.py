#!/usr/bin/env python3
"""Experiment 0002: causal multilingual hidden-bridge write smoke.

This is the first direct test of the desired external -> latent -> downstream
interface on a behavior-valid multilingual task.  It deliberately starts with
English and German because Qwen3.5-0.8B was 4/4 behaviorally correct in both
languages and J-lens ranked every hidden bridge at 1.  Thai remains a held-out
stress lane until the causal apparatus works where both prerequisites hold.

The same canonical English J-space country coordinate is used in both input
languages.  This is stricter than choosing a different decoder lexicalization
per language: a successful intervention must transfer across the surface
language without retuning the latent address.
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

TARGET_CONCEPT = {
    "country-france": "country-canada",
    "country-canada": "country-france",
    "country-germany": "country-japan",
    "country-japan": "country-germany",
}


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


def score_condition(
    hf_model,
    tokenizer,
    case: dict[str, Any],
    *,
    source_answer: str,
    target_answer: str,
) -> dict[str, Any]:
    scores = candidate_logprob_scores(
        hf_model,
        tokenizer,
        case["prompt"],
        case["language"],
        case["answer_candidates"],
    )
    by_candidate = candidate_map(scores)
    if source_answer not in by_candidate or target_answer not in by_candidate:
        raise ValueError(
            f"Source/target answers missing from candidates for {case['case_id']}: "
            f"{source_answer!r}, {target_answer!r}"
        )
    ordered = sorted(scores, key=lambda row: row["mean_logprob"], reverse=True)
    target_minus_source = by_candidate[target_answer] - by_candidate[source_answer]
    return {
        "predicted_answer": ordered[0]["candidate"],
        "candidate_scores": scores,
        "source_mean_logprob": by_candidate[source_answer],
        "target_mean_logprob": by_candidate[target_answer],
        "target_minus_source_margin": target_minus_source,
        "prefers_source": by_candidate[source_answer] > by_candidate[target_answer],
        "prefers_target": by_candidate[target_answer] > by_candidate[source_answer],
    }


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
        if case["language"] in languages and case["concept_id"] in TARGET_CONCEPT
    ]
    if not selected:
        raise ValueError("No cases selected for causal bridge smoke")

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

    # The first listed bridge surface in the validated fixture is the canonical
    # English lexicalization.  Use the same token coordinate in every language.
    canonical_surface: dict[str, str] = {}
    canonical_token: dict[str, int] = {}
    for concept_id in TARGET_CONCEPT:
        exemplars = [case for case in cases if case["concept_id"] == concept_id]
        if not exemplars:
            raise ValueError(f"Missing concept in fixture: {concept_id}")
        surface = exemplars[0]["intermediate_surfaces"][0]
        canonical_surface[concept_id] = surface
        canonical_token[concept_id] = single_token_id(tokenizer, surface)

    records: list[dict[str, Any]] = []
    conditions = {
        "late_bridge": (late_layers, "coordinate_swap"),
        "early_bridge": (early_layers, "coordinate_swap"),
        "late_random": (late_layers, "random_norm_matched"),
    }

    print(
        f"model={args.model} revision={resolved_revision} cases={len(selected)} "
        f"late={late_layers} early={early_layers} strength={args.strength}"
    )

    for case in selected:
        source_concept = case["concept_id"]
        target_concept = TARGET_CONCEPT[source_concept]
        target_case = case_by_key[(target_concept, case["language"])]
        source_answer = case["correct_answer"]
        target_answer = target_case["correct_answer"]
        prompt_len = len(
            tokenizer(case["prompt"], add_special_tokens=False).input_ids
        )

        baseline = score_condition(
            hf_model,
            tokenizer,
            case,
            source_answer=source_answer,
            target_answer=target_answer,
        )
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
                key=f"{case['case_id']}|{name}",
                position_limit=prompt_len,
            ):
                result = score_condition(
                    hf_model,
                    tokenizer,
                    case,
                    source_answer=source_answer,
                    target_answer=target_answer,
                )
            result["layers"] = layers
            result["mode"] = mode
            result["strength"] = args.strength
            result["margin_change_from_baseline"] = (
                result["target_minus_source_margin"]
                - baseline["target_minus_source_margin"]
            )
            result["strong_causal_success"] = (
                baseline["predicted_answer"] == source_answer
                and result["predicted_answer"] == target_answer
            )
            result["preference_flip"] = (
                baseline["prefers_source"] and result["prefers_target"]
            )
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
                    "late_margin_delta": row["conditions"]["late_bridge"]["margin_change_from_baseline"],
                    "early_margin_delta": row["conditions"]["early_bridge"]["margin_change_from_baseline"],
                    "random_margin_delta": row["conditions"]["late_random"]["margin_change_from_baseline"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    baseline_valid = [
        row for row in records if row["baseline"]["predicted_answer"] == row["source_answer"]
    ]
    condition_summary: dict[str, Any] = {}
    for name in conditions:
        values = [row["conditions"][name] for row in records]
        condition_summary[name] = {
            "n": len(values),
            "strong_causal_successes": sum(v["strong_causal_success"] for v in values),
            "preference_flips": sum(v["preference_flip"] for v in values),
            "mean_margin_change": mean(v["margin_change_from_baseline"] for v in values),
        }

    by_direction: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_direction[f"{row['source_concept']}->{row['target_concept']}"] .append(row)
    transfer_summary: dict[str, Any] = {}
    for direction, rows in sorted(by_direction.items()):
        late = [row["conditions"]["late_bridge"] for row in rows]
        transfer_summary[direction] = {
            "languages": sorted(row["language"] for row in rows),
            "all_languages_baseline_valid": all(
                row["baseline"]["predicted_answer"] == row["source_answer"] for row in rows
            ),
            "all_languages_strong_causal_success": all(
                value["strong_causal_success"] for value in late
            ),
            "all_languages_preference_flip": all(value["preference_flip"] for value in late),
            "mean_late_margin_change": mean(
                value["margin_change_from_baseline"] for value in late
            ),
        }

    summary = {
        "experiment": "0002-multilingual-hidden-bridge-causal-write",
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
        "baseline_valid_count": len(baseline_valid),
        "canonical_latent_surfaces": canonical_surface,
        "conditions": condition_summary,
        "cross_language_transfer": transfer_summary,
        "strong_evidence_rule": (
            "same canonical latent coordinate redirects behavior-valid English and German "
            "prompts to the counterfactual downstream capital while early-layer and "
            "norm-matched-random controls do not reproduce the effect"
        ),
        "interpretation": (
            "Causal write calibration only. Even a positive English/German result does not "
            "establish a general Neuralese ontology; Thai transfer and downstream function "
            "reuse remain separate promotion gates."
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
