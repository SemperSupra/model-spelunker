#!/usr/bin/env python3
"""Qwen3.5-4B + published Jacobian-lens compatibility smoke.

This is deliberately not a causal experiment. It verifies that the pinned
Anthropic HF adapter can locate the text decoder inside the multimodal
Qwen3.5 conditional-generation wrapper, that the published lens matches the
model width/layers, and that hidden country coordinates can be read on a tiny
set of already-qualified prompts.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch
from huggingface_hub import hf_hub_download, model_info
from transformers import AutoModelForImageTextToText, AutoTokenizer

import jlens
from run_multilingual_bridge_cloze import (
    FIT_POSITION_FLOOR,
    read_jsonl,
    resolve_single_token_surfaces,
    score_concept,
)

JLENS_UPSTREAM_COMMIT = "581d398613e5602a5af361e1c34d3a92ea82ba8e"
DEFAULT_MODEL = "Qwen/Qwen3.5-4B"
DEFAULT_LENS_REPO = "neuronpedia/jacobian-lens"
DEFAULT_LENS_REVISION = "91271eb5b15a43eebed7bb447618738754f1379a"
DEFAULT_LENS_FILE = (
    "qwen3.5-4b/jlens/Salesforce-wikitext/"
    "Qwen3.5-4B_jacobian_lens_n1000.pt"
)

SELECTED_CASES = {
    "bridge-cloze-lyon-en",
    "bridge-cloze-toronto-de",
    "bridge-cloze-munich-en",
    "bridge-cloze-osaka-de",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--fixture",
        default="fixtures/experiment-0002/multilingual-indirect-bridge-cloze.jsonl",
    )
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--revision", default="main")
    p.add_argument("--lens-repo", default=DEFAULT_LENS_REPO)
    p.add_argument("--lens-revision", default=DEFAULT_LENS_REVISION)
    p.add_argument("--lens-file", default=DEFAULT_LENS_FILE)
    p.add_argument("--positions", type=int, default=4)
    p.add_argument(
        "--output-dir",
        default="artifacts/experiment-0002-qwen35-4b-jlens-compat",
    )
    return p.parse_args()


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

    # Adopt the pinned upstream adapter unchanged. It explicitly supports
    # *ForConditionalGeneration and multimodal-wrapper layouts.
    model = jlens.from_hf(hf_model, tokenizer)

    lens_path = hf_hub_download(
        repo_id=args.lens_repo,
        filename=args.lens_file,
        revision=args.lens_revision,
    )
    lens = jlens.JacobianLens.load(lens_path)

    if lens.d_model != model.d_model:
        raise ValueError(f"Lens/model width mismatch: {lens.d_model} != {model.d_model}")
    if not lens.source_layers:
        raise ValueError("Published lens exposes no source layers")
    if max(lens.source_layers) >= model.n_layers:
        raise ValueError(
            f"Lens source layer {max(lens.source_layers)} exceeds model layers {model.n_layers}"
        )

    all_cases = read_jsonl(Path(args.fixture))
    cases = [case for case in all_cases if case["case_id"] in SELECTED_CASES]
    if {case["case_id"] for case in cases} != SELECTED_CASES:
        raise ValueError("Compatibility fixture is missing one or more selected cases")

    records: list[dict[str, Any]] = []
    for case in cases:
        lexicalizations = resolve_single_token_surfaces(
            tokenizer, case["intermediate_surfaces"]
        )
        if not lexicalizations:
            raise ValueError(f"No one-token bridge address for {case['case_id']}")

        input_ids = model.encode(case["prompt"])
        seq_len = int(input_ids.shape[-1])
        valid_positions = list(range(FIT_POSITION_FLOOR, seq_len))
        if not valid_positions:
            raise ValueError(f"No lens-fit position for {case['case_id']}")
        positions = valid_positions[-args.positions :]

        jlens_logits, _, _ = lens.apply(model, case["prompt"], positions=positions)
        score = score_concept(jlens_logits, lexicalizations, positions)
        del jlens_logits

        record = {
            "case_id": case["case_id"],
            "concept_id": case["concept_id"],
            "language": case["language"],
            "input_tokens": seq_len,
            "positions": positions,
            "best_rank": score["best_rank"],
            "best_surface": score["best_surface"],
            "best_layer": score["best_layer"],
            "best_position": score["best_position"],
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)

    summary = {
        "experiment": "0002-qwen35-4b-jlens-compatibility-smoke",
        "model": args.model,
        "resolved_model_revision": resolved_revision,
        "model_class": hf_model.__class__.__name__,
        "adapter_layout": {
            "path": model.layout.path,
            "layers": model.layout.layers,
            "norm": model.layout.norm,
            "embed": model.layout.embed,
            "lm_head": model.layout.lm_head,
        },
        "model_n_layers": model.n_layers,
        "model_d_model": model.d_model,
        "jlens_upstream_commit": JLENS_UPSTREAM_COMMIT,
        "lens_repo": args.lens_repo,
        "lens_revision": args.lens_revision,
        "lens_file": args.lens_file,
        "lens_n_prompts": lens.n_prompts,
        "lens_d_model": lens.d_model,
        "lens_source_layers": lens.source_layers,
        "case_count": len(records),
        "cases_top20": sum(row["best_rank"] <= 20 for row in records),
        "median_like_best_ranks": sorted(row["best_rank"] for row in records),
        "compatibility_pass": (
            len(records) == 4
            and lens.d_model == model.d_model
            and max(lens.source_layers) < model.n_layers
        ),
        "interpretation": (
            "Compatibility/observer calibration only. Passing proves that the pinned "
            "adapter and lens can be used on this wrapper; it is not causal evidence."
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
