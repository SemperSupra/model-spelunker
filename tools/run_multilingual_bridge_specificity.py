#!/usr/bin/env python3
"""Experiment 0002: matched-foil specificity control for multilingual bridge readout.

This is the smallest earned follow-up to the multilingual indirect-bridge cloze
rep. A low Jacobian-lens rank is not enough because searching many layer x
position x lexicalization cells can create false positives. For every prompt we
therefore score the true hidden country and all three matched foil countries in
exactly the same observer/search space.

Two specificity tests are reported for both J-lens and vanilla logit lens:

1. global-search specificity: does the true concept have a strictly better best
   rank than every foil after each concept searches the same cells?
2. anchor-cell specificity: at the layer/position where the TRUE concept is
   strongest, does it strictly outrank every foil at that exact cell?

The second test is the primary gate because it asks whether the discovered hit
is concept-specific rather than merely one of many unrelated rank-1 hits.
Observer evidence remains correlational; this script performs no intervention.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch
from huggingface_hub import hf_hub_download, model_info
from transformers import AutoModelForCausalLM, AutoTokenizer

import jlens

from run_multilingual_bridge_cloze import (
    DEFAULT_LENS_FILE,
    DEFAULT_LENS_REPO,
    DEFAULT_LENS_REVISION,
    DEFAULT_MODEL,
    FIT_POSITION_FLOOR,
    JLENS_UPSTREAM_COMMIT,
    candidate_logprob_scores,
    rank_of,
    read_jsonl,
    resolve_single_token_surfaces,
    score_concept,
)


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
    parser.add_argument("--positions", type=int, default=8)
    parser.add_argument(
        "--output-dir",
        default="artifacts/experiment-0002-multilingual-bridge-specificity",
    )
    return parser.parse_args()


def unique_surfaces_by_concept(cases: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for case in cases:
        bucket = out.setdefault(case["concept_id"], [])
        for surface in case["intermediate_surfaces"]:
            if surface not in bucket:
                bucket.append(surface)
    return out


def score_concept_at_cell(
    logits_by_layer: dict[int, torch.Tensor],
    lexicalizations: list[dict[str, Any]],
    positions: list[int],
    layer: int,
    position: int,
) -> dict[str, Any]:
    pos_index = positions.index(position)
    logits = logits_by_layer[layer][pos_index]
    rows = []
    for lexicalization in lexicalizations:
        rows.append(
            {
                **lexicalization,
                "rank": rank_of(logits, lexicalization["token_id"]),
            }
        )
    best = min(rows, key=lambda row: row["rank"])
    return {
        "rank": int(best["rank"]),
        "surface": best["surface"],
        "token_id": int(best["token_id"]),
        "all_lexicalizations": rows,
    }


def observer_specificity(
    logits_by_layer: dict[int, torch.Tensor],
    lexicalizations_by_concept: dict[str, list[dict[str, Any]]],
    positions: list[int],
    true_concept: str,
) -> dict[str, Any]:
    search_scores = {
        concept_id: score_concept(logits_by_layer, lexicalizations, positions)
        for concept_id, lexicalizations in lexicalizations_by_concept.items()
    }
    true_search = search_scores[true_concept]
    foil_search = {
        concept_id: score
        for concept_id, score in search_scores.items()
        if concept_id != true_concept
    }
    best_foil_search_rank = min(score["best_rank"] for score in foil_search.values())
    min_search_rank = min(score["best_rank"] for score in search_scores.values())
    global_tied_best = sorted(
        concept_id
        for concept_id, score in search_scores.items()
        if score["best_rank"] == min_search_rank
    )

    anchor_layer = int(true_search["best_layer"])
    anchor_position = int(true_search["best_position"])
    anchor_scores = {
        concept_id: score_concept_at_cell(
            logits_by_layer,
            lexicalizations,
            positions,
            anchor_layer,
            anchor_position,
        )
        for concept_id, lexicalizations in lexicalizations_by_concept.items()
    }
    true_anchor = anchor_scores[true_concept]
    foil_anchor = {
        concept_id: score
        for concept_id, score in anchor_scores.items()
        if concept_id != true_concept
    }
    best_foil_anchor_rank = min(score["rank"] for score in foil_anchor.values())
    min_anchor_rank = min(score["rank"] for score in anchor_scores.values())
    anchor_tied_best = sorted(
        concept_id
        for concept_id, score in anchor_scores.items()
        if score["rank"] == min_anchor_rank
    )

    return {
        "true_search": true_search,
        "search_scores": search_scores,
        "global_best_foil_rank": int(best_foil_search_rank),
        "global_rank_margin": int(best_foil_search_rank - true_search["best_rank"]),
        "global_true_strict_winner": bool(true_search["best_rank"] < best_foil_search_rank),
        "global_tied_best_concepts": global_tied_best,
        "anchor_layer": anchor_layer,
        "anchor_position": anchor_position,
        "anchor_scores": anchor_scores,
        "anchor_true_rank": int(true_anchor["rank"]),
        "anchor_true_surface": true_anchor["surface"],
        "anchor_best_foil_rank": int(best_foil_anchor_rank),
        "anchor_rank_margin": int(best_foil_anchor_rank - true_anchor["rank"]),
        "anchor_true_strict_winner": bool(true_anchor["rank"] < best_foil_anchor_rank),
        "anchor_tied_best_concepts": anchor_tied_best,
    }


def main() -> int:
    args = parse_args()
    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))
    cases = read_jsonl(Path(args.fixture))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(f"Could not resolve immutable revision for {args.model}@{args.revision}")

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
        raise ValueError(f"Lens/model d_model mismatch: {lens.d_model} != {model.d_model}")

    surfaces_by_concept = unique_surfaces_by_concept(cases)
    lexicalizations_by_concept = {
        concept_id: resolve_single_token_surfaces(tokenizer, surfaces)
        for concept_id, surfaces in surfaces_by_concept.items()
    }
    missing = [
        concept_id
        for concept_id, lexicalizations in lexicalizations_by_concept.items()
        if not lexicalizations
    ]
    if missing:
        raise ValueError(f"No single-token lexicalization for concepts: {missing}")

    # Map forced-choice answers back to their semantic country for error analysis.
    answer_to_concept: dict[str, dict[str, str]] = defaultdict(dict)
    for case in cases:
        answer_to_concept[case["language"]][case["correct_answer"]] = case["concept_id"]

    records: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    print(
        f"model={args.model} revision={resolved_revision} lens_n_prompts={lens.n_prompts} "
        f"layers={model.n_layers} cases={len(cases)} concepts={len(lexicalizations_by_concept)}"
    )
    print(
        "concept_lexicalizations="
        + json.dumps(
            {
                concept_id: [row["surface"] for row in rows]
                for concept_id, rows in lexicalizations_by_concept.items()
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    for case in cases:
        true_concept = case["concept_id"]
        leaked = [
            surface
            for surface in surfaces_by_concept[true_concept]
            if surface.strip() and surface.strip().casefold() in case["prompt"].casefold()
        ]
        if leaked:
            skipped.append(
                {
                    "case_id": case["case_id"],
                    "reason": "true_intermediate_surface_present_in_prompt",
                    "surfaces": leaked,
                }
            )
            continue

        input_ids = model.encode(case["prompt"])
        seq_len = int(input_ids.shape[-1])
        valid_positions = list(range(FIT_POSITION_FLOOR, seq_len))
        if not valid_positions:
            skipped.append(
                {
                    "case_id": case["case_id"],
                    "reason": "no_position_in_lens_fit_range",
                    "input_tokens": seq_len,
                }
            )
            continue
        positions = valid_positions[-args.positions :]

        jlens_logits, _, _ = lens.apply(model, case["prompt"], positions=positions)
        jlens_specificity = observer_specificity(
            jlens_logits,
            lexicalizations_by_concept,
            positions,
            true_concept,
        )
        del jlens_logits

        vanilla_logits, _, _ = lens.apply(
            model, case["prompt"], positions=positions, use_jacobian=False
        )
        vanilla_specificity = observer_specificity(
            vanilla_logits,
            lexicalizations_by_concept,
            positions,
            true_concept,
        )
        del vanilla_logits

        candidate_scores = candidate_logprob_scores(
            hf_model,
            tokenizer,
            case["prompt"],
            case["language"],
            case["answer_candidates"],
        )
        ordered = sorted(candidate_scores, key=lambda row: row["mean_logprob"], reverse=True)
        predicted = ordered[0]["candidate"]
        behavior_correct = predicted == case["correct_answer"]
        correct_row = next(
            row for row in candidate_scores if row["candidate"] == case["correct_answer"]
        )
        behavior_margin = correct_row["mean_logprob"] - max(
            row["mean_logprob"]
            for row in candidate_scores
            if row["candidate"] != case["correct_answer"]
        )
        selected_concept = answer_to_concept[case["language"]].get(predicted)

        record = {
            "case_id": case["case_id"],
            "concept_id": true_concept,
            "language": case["language"],
            "prompt": case["prompt"],
            "prompt_sha256": hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest(),
            "input_tokens": seq_len,
            "scored_positions": positions,
            "correct_answer": case["correct_answer"],
            "predicted_answer": predicted,
            "behavior_selected_concept": selected_concept,
            "behavior_correct": behavior_correct,
            "behavior_margin_mean_logprob": float(behavior_margin),
            "candidate_scores": candidate_scores,
            "jlens": jlens_specificity,
            "vanilla": vanilla_specificity,
        }
        records.append(record)
        print(
            json.dumps(
                {
                    "case_id": case["case_id"],
                    "behavior_ok": behavior_correct,
                    "predicted": predicted,
                    "selected_concept": selected_concept,
                    "jlens_true_rank": jlens_specificity["true_search"]["best_rank"],
                    "jlens_global_margin": jlens_specificity["global_rank_margin"],
                    "jlens_global_strict": jlens_specificity["global_true_strict_winner"],
                    "jlens_anchor_margin": jlens_specificity["anchor_rank_margin"],
                    "jlens_anchor_strict": jlens_specificity["anchor_true_strict_winner"],
                    "jlens_anchor_ties": jlens_specificity["anchor_tied_best_concepts"],
                    "vanilla_anchor_strict": vanilla_specificity["anchor_true_strict_winner"],
                },
                ensure_ascii=False,
            )
        )

    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_language[row["language"]].append(row)
        by_concept[row["concept_id"]].append(row)

    def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = max(1, len(rows))
        return {
            "n": len(rows),
            "behavior_accuracy": sum(row["behavior_correct"] for row in rows) / n,
            "jlens_global_specificity_rate": sum(
                row["jlens"]["global_true_strict_winner"] for row in rows
            ) / n,
            "jlens_anchor_specificity_rate": sum(
                row["jlens"]["anchor_true_strict_winner"] for row in rows
            ) / n,
            "vanilla_anchor_specificity_rate": sum(
                row["vanilla"]["anchor_true_strict_winner"] for row in rows
            ) / n,
            "median_jlens_anchor_margin": float(
                median(row["jlens"]["anchor_rank_margin"] for row in rows)
            ) if rows else None,
            "behavior_wrong_but_jlens_anchor_specific": sum(
                (not row["behavior_correct"]) and row["jlens"]["anchor_true_strict_winner"]
                for row in rows
            ),
            "behavior_correct_but_jlens_anchor_nonspecific": sum(
                row["behavior_correct"] and (not row["jlens"]["anchor_true_strict_winner"])
                for row in rows
            ),
        }

    language_summary = {
        language: summarize_rows(rows)
        for language, rows in sorted(by_language.items())
    }

    concept_summary: dict[str, Any] = {}
    for concept_id, rows in sorted(by_concept.items()):
        langs = {row["language"] for row in rows}
        concept_summary[concept_id] = {
            **summarize_rows(rows),
            "languages": sorted(langs),
            "all_three_languages_present": langs == {"en", "de", "th"},
            "all_languages_behavior_correct": bool(rows)
            and all(row["behavior_correct"] for row in rows),
            "all_languages_jlens_anchor_specific": bool(rows)
            and all(row["jlens"]["anchor_true_strict_winner"] for row in rows),
            "per_language": {
                row["language"]: {
                    "behavior_correct": row["behavior_correct"],
                    "jlens_true_best_rank": row["jlens"]["true_search"]["best_rank"],
                    "jlens_anchor_margin": row["jlens"]["anchor_rank_margin"],
                    "jlens_anchor_specific": row["jlens"]["anchor_true_strict_winner"],
                }
                for row in rows
            },
        }

    promotion_concepts = [
        concept_id
        for concept_id, row in concept_summary.items()
        if row["all_languages_behavior_correct"]
        and row["all_languages_jlens_anchor_specific"]
    ]

    summary = {
        "experiment": "0002-multilingual-indirect-bridge-specificity",
        "model": args.model,
        "model_class": hf_model.__class__.__name__,
        "requested_revision": args.revision,
        "resolved_model_revision": resolved_revision,
        "jlens_upstream_commit": JLENS_UPSTREAM_COMMIT,
        "lens_repo": args.lens_repo,
        "lens_revision": args.lens_revision,
        "lens_file": args.lens_file,
        "lens_n_prompts": lens.n_prompts,
        "lens_d_model": lens.d_model,
        "lens_source_layers": lens.source_layers,
        "fit_position_floor": FIT_POSITION_FLOOR,
        "case_count": len(cases),
        "evaluated_cases": len(records),
        "skipped_cases": len(skipped),
        "concept_lexicalizations": {
            concept_id: [row["surface"] for row in lexicalizations]
            for concept_id, lexicalizations in lexicalizations_by_concept.items()
        },
        "overall": summarize_rows(records),
        "language_summary": language_summary,
        "concept_summary": concept_summary,
        "promotion_concepts": promotion_concepts,
        "causal_cross_language_write_earned": len(promotion_concepts) >= 2,
        "promotion_rule": (
            "Run the cross-language causal write only after at least two concepts are both "
            "behaviorally correct and J-lens anchor-specific in English, German, and Thai. "
            "A low true-concept rank without matched-foil specificity does not qualify."
        ),
        "interpretation": (
            "This is an observer specificity control, not a causal Neuralese result. "
            "Behavior-wrong/J-lens-specific cases are retained as present-vs-used candidates "
            "but do not independently earn a representation claim."
        ),
    }

    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out_dir / "skipped.jsonl").open("w", encoding="utf-8") as handle:
        for row in skipped:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
