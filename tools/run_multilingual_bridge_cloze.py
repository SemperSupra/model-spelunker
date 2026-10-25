#!/usr/bin/env python3
"""Experiment 0002: multilingual indirect-bridge cloze calibration.

Version 2 of the cheap observer rep fixes two confounds from the first run:

1. surface competence is measured by forced-choice continuation likelihood,
   not short free generation that can be consumed by model-specific thinking
   wrappers;
2. the hidden concept is read through every supplied lexicalization that is a
   single tokenizer token, rather than assuming its English label is the only
   valid decoder coordinate.

The prompt still never names the hidden country. We therefore test:

    different external language surfaces -> implied bridge concept -> answer

Observer evidence is still non-causal and cannot establish addressable
Neuralese without a later write/erase/reuse intervention.
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

FIT_POSITION_FLOOR = 16
JLENS_UPSTREAM_COMMIT = "581d398613e5602a5af361e1c34d3a92ea82ba8e"
DEFAULT_MODEL = "Qwen/Qwen3.5-0.8B"
DEFAULT_LENS_REPO = "neuronpedia/jacobian-lens"
DEFAULT_LENS_REVISION = "4f30bb8c97e696115d4a2ef359923b5005fc860c"
DEFAULT_LENS_FILE = (
    "qwen3.5-0.8b/jlens/Salesforce-wikitext/"
    "Qwen3.5-0.8B_jacobian_lens.pt"
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
        default="artifacts/experiment-0002-multilingual-bridge-cloze",
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def rank_of(logits: torch.Tensor, token_id: int) -> int:
    target = logits[token_id]
    return int((logits > target).sum().item()) + 1


def resolve_single_token_surfaces(tokenizer, surfaces: list[str]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for surface in surfaces:
        ids = tokenizer(surface, add_special_tokens=False).input_ids
        if len(ids) != 1:
            continue
        token_id = int(ids[0])
        if token_id in seen_ids:
            continue
        seen_ids.add(token_id)
        resolved.append(
            {
                "surface": surface,
                "token_id": token_id,
                "decoded": tokenizer.decode([token_id], skip_special_tokens=False),
            }
        )
    return resolved


def score_one_surface(
    logits_by_layer: dict[int, torch.Tensor],
    token_id: int,
    positions: list[int],
) -> dict[str, Any]:
    cells: list[tuple[int, int, int]] = []
    layer_best: list[int] = []
    for layer, logits in logits_by_layer.items():
        ranks = [rank_of(logits[i], token_id) for i in range(logits.shape[0])]
        layer_best.append(min(ranks))
        cells.extend(
            (int(rank), int(layer), int(positions[i]))
            for i, rank in enumerate(ranks)
        )
    best_rank, best_layer, best_position = min(cells, key=lambda row: row[0])
    return {
        "best_rank": best_rank,
        "best_layer": best_layer,
        "best_position": best_position,
        "median_layer_best_rank": float(median(layer_best)),
        "top5_cells": sum(rank <= 5 for rank, _, _ in cells),
        "top20_cells": sum(rank <= 20 for rank, _, _ in cells),
        "scored_cells": len(cells),
    }


def score_concept(
    logits_by_layer: dict[int, torch.Tensor],
    lexicalizations: list[dict[str, Any]],
    positions: list[int],
) -> dict[str, Any]:
    surface_scores: list[dict[str, Any]] = []
    for lexicalization in lexicalizations:
        score = score_one_surface(
            logits_by_layer, lexicalization["token_id"], positions
        )
        surface_scores.append({**lexicalization, **score})
    best = min(surface_scores, key=lambda row: row["best_rank"])
    return {
        "best_rank": best["best_rank"],
        "best_surface": best["surface"],
        "best_token_id": best["token_id"],
        "best_layer": best["best_layer"],
        "best_position": best["best_position"],
        "median_surface_best_rank": float(
            median(row["best_rank"] for row in surface_scores)
        ),
        "surface_scores": surface_scores,
    }


def continuation_text(language: str, candidate: str) -> str:
    # English/German word completions conventionally need a leading space;
    # Thai does not use inter-word spaces in the same way.
    return candidate if language == "th" else f" {candidate}"


def candidate_logprob_scores(
    hf_model,
    tokenizer,
    prompt: str,
    language: str,
    candidates: list[str],
) -> list[dict[str, Any]]:
    """Score all continuation candidates in one padded forward pass.

    The metric is mean token log probability so Thai candidates are not
    penalized merely for tokenizing into more pieces than Latin-script names.
    """
    prompt_ids = tokenizer(prompt, add_special_tokens=False).input_ids
    rows: list[dict[str, Any]] = []
    max_len = 0
    for candidate in candidates:
        continuation = continuation_text(language, candidate)
        full_ids = tokenizer(
            prompt + continuation, add_special_tokens=False
        ).input_ids
        if full_ids[: len(prompt_ids)] != prompt_ids:
            raise ValueError(
                f"Tokenizer prefix changed when appending candidate {candidate!r}"
            )
        start = len(prompt_ids)
        if len(full_ids) <= start:
            raise ValueError(f"Candidate produced no continuation tokens: {candidate!r}")
        rows.append(
            {
                "candidate": candidate,
                "input_ids": full_ids,
                "start": start,
                "continuation_token_count": len(full_ids) - start,
            }
        )
        max_len = max(max_len, len(full_ids))

    pad_id = tokenizer.pad_token_id
    if pad_id is None:
        pad_id = tokenizer.eos_token_id
    if pad_id is None:
        raise ValueError("Tokenizer has neither pad_token_id nor eos_token_id")

    batch_ids = torch.full(
        (len(rows), max_len), int(pad_id), dtype=torch.long, device="cpu"
    )
    attention = torch.zeros_like(batch_ids)
    for i, row in enumerate(rows):
        ids = torch.tensor(row["input_ids"], dtype=torch.long)
        batch_ids[i, : len(ids)] = ids
        attention[i, : len(ids)] = 1

    with torch.inference_mode():
        logits = hf_model(
            input_ids=batch_ids, attention_mask=attention, use_cache=False
        ).logits.float()
        log_probs = torch.log_softmax(logits, dim=-1)

    scored: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        ids = row["input_ids"]
        start = int(row["start"])
        token_logps: list[float] = []
        for pos in range(start, len(ids)):
            if pos == 0:
                raise ValueError("Cannot score continuation token at absolute position 0")
            token_logps.append(float(log_probs[i, pos - 1, ids[pos]].item()))
        scored.append(
            {
                "candidate": row["candidate"],
                "continuation_token_count": row["continuation_token_count"],
                "sum_logprob": float(sum(token_logps)),
                "mean_logprob": float(sum(token_logps) / len(token_logps)),
            }
        )
    return scored


def main() -> int:
    args = parse_args()
    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))
    cases = read_jsonl(Path(args.fixture))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(
            f"Could not resolve immutable revision for {args.model}@{args.revision}"
        )

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
        raise ValueError(
            f"Lens/model d_model mismatch: {lens.d_model} != {model.d_model}"
        )

    records: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    print(
        f"model={args.model} revision={resolved_revision} lens_n_prompts={lens.n_prompts} "
        f"layers={model.n_layers} cases={len(cases)}"
    )

    for case in cases:
        # No supplied bridge lexicalization may already be in the prompt.
        leaked = [
            surface
            for surface in case["intermediate_surfaces"]
            if surface.strip() and surface.strip().casefold() in case["prompt"].casefold()
        ]
        if leaked:
            skipped.append(
                {
                    "case_id": case["case_id"],
                    "reason": "intermediate_surface_present_in_prompt",
                    "surfaces": leaked,
                }
            )
            continue

        lexicalizations = resolve_single_token_surfaces(
            tokenizer, case["intermediate_surfaces"]
        )
        if not lexicalizations:
            skipped.append(
                {
                    "case_id": case["case_id"],
                    "reason": "no_single_token_intermediate_lexicalization",
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
        jlens_score = score_concept(jlens_logits, lexicalizations, positions)
        del jlens_logits

        vanilla_logits, _, _ = lens.apply(
            model, case["prompt"], positions=positions, use_jacobian=False
        )
        vanilla_score = score_concept(vanilla_logits, lexicalizations, positions)
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
        correct = predicted == case["correct_answer"]
        correct_row = next(
            row for row in candidate_scores if row["candidate"] == case["correct_answer"]
        )
        behavior_margin = correct_row["mean_logprob"] - max(
            row["mean_logprob"]
            for row in candidate_scores
            if row["candidate"] != case["correct_answer"]
        )

        record = {
            "case_id": case["case_id"],
            "concept_id": case["concept_id"],
            "language": case["language"],
            "prompt": case["prompt"],
            "prompt_sha256": hashlib.sha256(
                case["prompt"].encode("utf-8")
            ).hexdigest(),
            "input_tokens": seq_len,
            "scored_positions": positions,
            "lexicalizations": lexicalizations,
            "correct_answer": case["correct_answer"],
            "answer_candidates": case["answer_candidates"],
            "candidate_scores": candidate_scores,
            "predicted_answer": predicted,
            "behavior_correct": correct,
            "behavior_margin_mean_logprob": behavior_margin,
            "jlens": jlens_score,
            "vanilla": vanilla_score,
            "best_rank_improvement": (
                vanilla_score["best_rank"] - jlens_score["best_rank"]
            ),
        }
        records.append(record)
        print(
            json.dumps(
                {
                    "case_id": record["case_id"],
                    "tokens": seq_len,
                    "lexicalizations": [row["surface"] for row in lexicalizations],
                    "predicted": predicted,
                    "correct": case["correct_answer"],
                    "behavior_ok": correct,
                    "behavior_margin": behavior_margin,
                    "jlens_best": jlens_score["best_rank"],
                    "jlens_surface": jlens_score["best_surface"],
                    "vanilla_best": vanilla_score["best_rank"],
                },
                ensure_ascii=False,
            )
        )

    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_language[row["language"]].append(row)
        by_concept[row["concept_id"]].append(row)

    language_summary: dict[str, Any] = {}
    for language, rows in sorted(by_language.items()):
        language_summary[language] = {
            "n": len(rows),
            "behavior_accuracy": sum(row["behavior_correct"] for row in rows)
            / max(1, len(rows)),
            "median_behavior_margin": float(
                median(row["behavior_margin_mean_logprob"] for row in rows)
            ),
            "jlens_beats_vanilla_best_rank": sum(
                row["jlens"]["best_rank"] < row["vanilla"]["best_rank"]
                for row in rows
            ),
            "median_jlens_best_rank": float(
                median(row["jlens"]["best_rank"] for row in rows)
            ),
            "median_vanilla_best_rank": float(
                median(row["vanilla"]["best_rank"] for row in rows)
            ),
        }

    concept_summary: dict[str, Any] = {}
    for concept_id, rows in sorted(by_concept.items()):
        langs = {row["language"] for row in rows}
        concept_summary[concept_id] = {
            "languages": sorted(langs),
            "all_three_languages_present": langs == {"en", "de", "th"},
            "all_languages_behavior_correct": bool(rows)
            and all(row["behavior_correct"] for row in rows),
            "all_languages_jlens_top20_somewhere": bool(rows)
            and all(row["jlens"]["best_rank"] <= 20 for row in rows),
            "best_ranks": {
                row["language"]: row["jlens"]["best_rank"] for row in rows
            },
            "best_surfaces": {
                row["language"]: row["jlens"]["best_surface"] for row in rows
            },
        }

    summary = {
        "experiment": "0002-multilingual-indirect-bridge-cloze",
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
        "behavior_accuracy": sum(row["behavior_correct"] for row in records)
        / max(1, len(records)),
        "cases_where_jlens_best_rank_beats_vanilla": sum(
            row["jlens"]["best_rank"] < row["vanilla"]["best_rank"]
            for row in records
        ),
        "language_summary": language_summary,
        "concept_summary": concept_summary,
        "promotion_rule": (
            "A causal cross-language write is earned only if multiple concepts are behaviorally "
            "competent and the hidden bridge is observable in all three languages under matched "
            "controls. Otherwise improve the observer/task or move to a stronger model first."
        ),
        "interpretation": (
            "observer-only evidence. Multiple lexicalizations reduce decoder-language bias, but "
            "readout success remains correlational until causal write/erase and multi-task reuse."
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
