#!/usr/bin/env python3
"""Experiment 0002: multilingual indirect-bridge observer calibration.

This is a cheap Phase-A rep for the external->latent interface hypothesis.
Matched English/German/Thai prompts imply an intermediate entity without naming
it (e.g. Lyon -> France -> Paris). We ask whether a published Jacobian lens
recovers the same hidden bridge entity across languages more clearly than an
ordinary logit lens, while separately recording whether the model can solve the
surface task.

Important constraints:
- no causal/Neuralese claim is earned by this observer-only run;
- the intermediate entity must not appear verbatim in the prompt;
- only positions >= 16 are scored because the pinned Jacobian-lens fitter
  excludes the first 16 positions as attention-sink / atypical statistics;
- J-lens and vanilla logit-lens scores search exactly the same layer/position
  space so the comparison is paired.
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
        "--fixture", default="fixtures/experiment-0002/multilingual-indirect-bridge.jsonl"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--lens-repo", default=DEFAULT_LENS_REPO)
    parser.add_argument("--lens-revision", default=DEFAULT_LENS_REVISION)
    parser.add_argument("--lens-file", default=DEFAULT_LENS_FILE)
    parser.add_argument("--positions", type=int, default=8,
                        help="score only this many trailing fitted-range prompt positions")
    parser.add_argument("--max-new-tokens", type=int, default=8)
    parser.add_argument(
        "--output-dir", default="artifacts/experiment-0002-multilingual-bridge-observer"
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def rank_of(logits: torch.Tensor, token_id: int) -> int:
    target = logits[token_id]
    return int((logits > target).sum().item()) + 1


def target_token_id(tokenizer, surface: str) -> int:
    ids = tokenizer(surface, add_special_tokens=False).input_ids
    if len(ids) != 1:
        raise ValueError(f"Intermediate must be one token for vocabulary-rank readout: {surface!r} -> {ids}")
    return int(ids[0])


def normalize_text(text: str) -> str:
    return " ".join(text.casefold().strip().split())


def answer_matches(text: str, aliases: list[str]) -> bool:
    clean = normalize_text(text).lstrip('"\'`.,:;!?-— ')
    return any(normalize_text(alias) in clean for alias in aliases)


def load_hf_model(model_id: str, revision: str):
    """Load a text CausalLM when possible, otherwise a multimodal text generator.

    Qwen3.5 is distributed as *ForConditionalGeneration even for text-only use.
    Keep this compatibility shim local to the experiment rather than expanding
    the shared harness until another experiment needs it.
    """
    try:
        return AutoModelForCausalLM.from_pretrained(
            model_id, revision=revision, dtype=torch.float32
        )
    except (ValueError, TypeError):
        try:
            from transformers import AutoModelForImageTextToText

            return AutoModelForImageTextToText.from_pretrained(
                model_id, revision=revision, dtype=torch.float32
            )
        except ImportError:
            from transformers import AutoModelForVision2Seq

            return AutoModelForVision2Seq.from_pretrained(
                model_id, revision=revision, dtype=torch.float32
            )


def generate_text(hf_model, tokenizer, prompt: str, max_new_tokens: int) -> str:
    encoded = tokenizer(prompt, return_tensors="pt")
    input_ids = encoded.input_ids.to("cpu")
    attention_mask = getattr(encoded, "attention_mask", None)
    kwargs = {"input_ids": input_ids, "max_new_tokens": max_new_tokens, "do_sample": False}
    if attention_mask is not None:
        kwargs["attention_mask"] = attention_mask.to("cpu")
    if tokenizer.eos_token_id is not None:
        kwargs["pad_token_id"] = tokenizer.eos_token_id
    with torch.inference_mode():
        generated = hf_model.generate(**kwargs)
    continuation = generated[0, input_ids.shape[-1]:]
    return tokenizer.decode(continuation, skip_special_tokens=True)


def score_lens_output(
    logits_by_layer: dict[int, torch.Tensor], token_id: int, positions: list[int]
) -> dict[str, Any]:
    per_layer: list[dict[str, Any]] = []
    all_cells: list[tuple[int, int, int]] = []
    for layer, logits in logits_by_layer.items():
        ranks = [rank_of(logits[i], token_id) for i in range(logits.shape[0])]
        best_idx = min(range(len(ranks)), key=ranks.__getitem__)
        per_layer.append(
            {
                "layer": int(layer),
                "best_rank": int(ranks[best_idx]),
                "best_position": int(positions[best_idx]),
            }
        )
        all_cells.extend((int(rank), int(layer), int(positions[i])) for i, rank in enumerate(ranks))

    best_rank, best_layer, best_position = min(all_cells, key=lambda row: row[0])
    layer_best = [row["best_rank"] for row in per_layer]
    return {
        "best_rank": best_rank,
        "best_layer": best_layer,
        "best_position": best_position,
        "median_layer_best_rank": float(median(layer_best)),
        "top5_cells": sum(rank <= 5 for rank, _, _ in all_cells),
        "top20_cells": sum(rank <= 20 for rank, _, _ in all_cells),
        "scored_cells": len(all_cells),
        "per_layer": per_layer,
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
    hf_model = load_hf_model(args.model, resolved_revision)
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

    records: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    print(
        f"model={args.model} class={hf_model.__class__.__name__} revision={resolved_revision} "
        f"layers={model.n_layers} lens_layers={lens.source_layers} cases={len(cases)}"
    )

    for case in cases:
        stripped_intermediate = case["intermediate"].strip().casefold()
        if stripped_intermediate in case["prompt"].casefold():
            skipped.append({"case_id": case["case_id"], "reason": "intermediate_surface_present_in_prompt"})
            continue

        token_id = target_token_id(tokenizer, case["intermediate"])
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
        positions = valid_positions[-args.positions:]

        lens_logits, _, _ = lens.apply(model, case["prompt"], positions=positions)
        jlens_score = score_lens_output(lens_logits, token_id, positions)
        del lens_logits

        vanilla_logits, _, _ = lens.apply(
            model, case["prompt"], positions=positions, use_jacobian=False
        )
        vanilla_score = score_lens_output(vanilla_logits, token_id, positions)
        del vanilla_logits

        continuation = generate_text(hf_model, tokenizer, case["prompt"], args.max_new_tokens)
        behavior_correct = answer_matches(continuation, case["answer_aliases"])

        record = {
            "case_id": case["case_id"],
            "concept_id": case["concept_id"],
            "language": case["language"],
            "prompt": case["prompt"],
            "prompt_sha256": hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest(),
            "input_tokens": seq_len,
            "scored_positions": positions,
            "intermediate": case["intermediate"],
            "intermediate_token_id": token_id,
            "answer_aliases": case["answer_aliases"],
            "continuation": continuation,
            "behavior_correct": behavior_correct,
            "jlens": jlens_score,
            "vanilla": vanilla_score,
            "best_rank_improvement": vanilla_score["best_rank"] - jlens_score["best_rank"],
            "median_layer_best_rank_improvement": (
                vanilla_score["median_layer_best_rank"] - jlens_score["median_layer_best_rank"]
            ),
        }
        records.append(record)
        print(
            json.dumps(
                {
                    "case_id": record["case_id"],
                    "tokens": seq_len,
                    "behavior_correct": behavior_correct,
                    "continuation": continuation,
                    "jlens_best": jlens_score["best_rank"],
                    "vanilla_best": vanilla_score["best_rank"],
                    "jlens_median_layer_best": jlens_score["median_layer_best_rank"],
                    "vanilla_median_layer_best": vanilla_score["median_layer_best_rank"],
                },
                ensure_ascii=False,
            )
        )

    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_language[row["language"]].append(row)
        by_concept[row["concept_id"]].append(row)

    language_summary = {}
    for language, rows in sorted(by_language.items()):
        language_summary[language] = {
            "n": len(rows),
            "behavior_accuracy": sum(row["behavior_correct"] for row in rows) / max(1, len(rows)),
            "jlens_beats_vanilla_best_rank": sum(
                row["jlens"]["best_rank"] < row["vanilla"]["best_rank"] for row in rows
            ),
            "median_jlens_best_rank": float(median(row["jlens"]["best_rank"] for row in rows)),
            "median_vanilla_best_rank": float(median(row["vanilla"]["best_rank"] for row in rows)),
            "median_jlens_layer_best_rank": float(
                median(row["jlens"]["median_layer_best_rank"] for row in rows)
            ),
            "median_vanilla_layer_best_rank": float(
                median(row["vanilla"]["median_layer_best_rank"] for row in rows)
            ),
        }

    concept_summary = {}
    for concept_id, rows in sorted(by_concept.items()):
        langs = {row["language"] for row in rows}
        concept_summary[concept_id] = {
            "languages": sorted(langs),
            "all_three_languages_present": langs == {"en", "de", "th"},
            "all_languages_behavior_correct": bool(rows) and all(row["behavior_correct"] for row in rows),
            "all_languages_jlens_top20_somewhere": bool(rows) and all(
                row["jlens"]["best_rank"] <= 20 for row in rows
            ),
            "best_ranks": {row["language"]: row["jlens"]["best_rank"] for row in rows},
        }

    summary = {
        "experiment": "0002-multilingual-indirect-bridge-observer",
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
        "behavior_accuracy": sum(row["behavior_correct"] for row in records) / max(1, len(records)),
        "cases_where_jlens_best_rank_beats_vanilla": sum(
            row["jlens"]["best_rank"] < row["vanilla"]["best_rank"] for row in records
        ),
        "language_summary": language_summary,
        "concept_summary": concept_summary,
        "interpretation": (
            "observer-only calibration of different external language surfaces -> implied latent bridge. "
            "No causal/addressable-Neuralese claim is permitted until write/erase, matched controls, "
            "and downstream reuse succeed."
        ),
    }

    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out_dir / "skipped.jsonl").open("w", encoding="utf-8") as handle:
        for row in skipped:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
