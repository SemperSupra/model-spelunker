#!/usr/bin/env python3
"""Calibrate Anthropic's Jacobian-lens observer on a published pre-fitted lens.

This does not test our Neuralese hypothesis directly. It asks a narrower question:
does the imported observer expose a specified hidden intermediate more clearly than a
vanilla logit lens on a model/lens pair for which a pre-fitted lens is available?
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch
from huggingface_hub import hf_hub_download, model_info
from transformers import AutoModelForCausalLM, AutoTokenizer

import jlens


DEFAULT_MODEL = "EleutherAI/pythia-70m-deduped"
DEFAULT_LENS_REPO = "neuronpedia/jacobian-lens"
DEFAULT_LENS_REVISION = "91271eb5b15a43eebed7bb447618738754f1379a"
DEFAULT_LENS_FILE = (
    "pythia-70m-deduped/jlens/Salesforce-wikitext/"
    "pythia-70m-deduped_jacobian_lens.pt"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture", default="fixtures/experiment-0002/jlens-observer-smoke.jsonl"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--lens-repo", default=DEFAULT_LENS_REPO)
    parser.add_argument("--lens-revision", default=DEFAULT_LENS_REVISION)
    parser.add_argument("--lens-file", default=DEFAULT_LENS_FILE)
    parser.add_argument("--output-dir", default="artifacts/experiment-0002-jlens-observer")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def single_token_id(tokenizer, text: str) -> int:
    ids = tokenizer(text, add_special_tokens=False).input_ids
    if len(ids) != 1:
        raise ValueError(
            f"Observer smoke targets must be one token for rank comparison: {text!r} -> {ids}"
        )
    return int(ids[0])


def rank_of(logits: torch.Tensor, token_id: int) -> int:
    target = logits[token_id]
    return int((logits > target).sum().item()) + 1


def explicit_layout_for(hf_model) -> jlens.Layout | None:
    """Bridge known API drift without modifying the pinned upstream package.

    Anthropic's 2026-07 reference adapter names GPT-NeoX/Pythia's unembedding
    ``embed_out``. Current Transformers exposes the same CausalLM head as
    ``lm_head``. Detect that narrow compatibility case and provide the explicit
    upstream Layout object; all other families continue through upstream
    auto-detection.
    """
    if (
        hf_model.__class__.__name__ == "GPTNeoXForCausalLM"
        and hasattr(hf_model, "gpt_neox")
        and hasattr(hf_model, "lm_head")
    ):
        return jlens.Layout(
            path="gpt_neox",
            layers="layers",
            norm="final_layer_norm",
            embed="embed_in",
            lm_head="lm_head",
        )
    return None


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = read_jsonl(Path(args.fixture))

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(
            f"Could not resolve immutable revision for {args.model}@{args.revision}"
        )

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    hf_model = AutoModelForCausalLM.from_pretrained(
        args.model, revision=resolved_revision
    )
    hf_model.eval().to("cpu")
    explicit_layout = explicit_layout_for(hf_model)
    model = jlens.from_hf(hf_model, tokenizer, layout=explicit_layout)

    # The upstream convenience loader uses snapshot_download, which first lists
    # the entire lens repository. We already know the exact immutable revision
    # and exact file, so fetch that file directly to reduce Hub requests and
    # avoid repository-tree rate-limit failures on anonymous public runners.
    lens_path = hf_hub_download(
        repo_id=args.lens_repo,
        filename=args.lens_file,
        revision=args.lens_revision,
    )
    lens = jlens.JacobianLens.load(lens_path)
    if lens.d_model != model.d_model:
        raise ValueError(
            f"Lens/model d_model mismatch: lens={lens.d_model}, model={model.d_model}"
        )

    records: list[dict[str, Any]] = []
    for case in cases:
        target_id = single_token_id(tokenizer, case["intermediate"])
        lens_logits, _, input_ids = lens.apply(
            model, case["prompt"], positions=[-1]
        )
        vanilla_logits, _, _ = lens.apply(
            model, case["prompt"], positions=[-1], use_jacobian=False
        )

        per_layer = []
        for layer in lens.source_layers:
            jl_rank = rank_of(lens_logits[layer][0], target_id)
            vanilla_rank = rank_of(vanilla_logits[layer][0], target_id)
            per_layer.append(
                {
                    "layer": layer,
                    "jlens_rank": jl_rank,
                    "vanilla_rank": vanilla_rank,
                    "rank_improvement": vanilla_rank - jl_rank,
                }
            )

        best_jlens = min(per_layer, key=lambda row: row["jlens_rank"])
        best_vanilla = min(per_layer, key=lambda row: row["vanilla_rank"])
        best_improvement = max(per_layer, key=lambda row: row["rank_improvement"])
        record = {
            "case_id": case["case_id"],
            "prompt": case["prompt"],
            "intermediate": case["intermediate"],
            "downstream": case["downstream"],
            "input_tokens": int(input_ids.shape[-1]),
            "target_token_id": target_id,
            "best_jlens_rank": best_jlens["jlens_rank"],
            "best_jlens_layer": best_jlens["layer"],
            "best_vanilla_rank": best_vanilla["vanilla_rank"],
            "best_vanilla_layer": best_vanilla["layer"],
            "best_rank_improvement": best_improvement["rank_improvement"],
            "best_improvement_layer": best_improvement["layer"],
            "per_layer": per_layer,
        }
        records.append(record)
        print(
            json.dumps(
                {
                    k: record[k]
                    for k in (
                        "case_id",
                        "intermediate",
                        "best_jlens_rank",
                        "best_jlens_layer",
                        "best_vanilla_rank",
                        "best_vanilla_layer",
                        "best_rank_improvement",
                    )
                },
                ensure_ascii=False,
            )
        )

    improved_cases = sum(
        1 for row in records if row["best_jlens_rank"] < row["best_vanilla_rank"]
    )
    median_best_jlens = sorted(row["best_jlens_rank"] for row in records)[
        len(records) // 2
    ]
    median_best_vanilla = sorted(row["best_vanilla_rank"] for row in records)[
        len(records) // 2
    ]
    summary = {
        "experiment": "0002-jlens-observer-calibration",
        "model": args.model,
        "model_class": hf_model.__class__.__name__,
        "resolved_model_revision": resolved_revision,
        "jlens_upstream_commit": "581d398613e5602a5af361e1c34d3a92ea82ba8e",
        "adapter_layout": None
        if explicit_layout is None
        else {
            "path": explicit_layout.path,
            "layers": explicit_layout.layers,
            "norm": explicit_layout.norm,
            "embed": explicit_layout.embed,
            "lm_head": explicit_layout.lm_head,
        },
        "lens_repo": args.lens_repo,
        "lens_revision": args.lens_revision,
        "lens_file": args.lens_file,
        "lens_n_prompts": lens.n_prompts,
        "lens_d_model": lens.d_model,
        "case_count": len(records),
        "cases_where_best_jlens_rank_beats_best_vanilla": improved_cases,
        "median_best_jlens_rank": median_best_jlens,
        "median_best_vanilla_rank": median_best_vanilla,
        "interpretation": (
            "observer calibration only; target ranks are not evidence of an addressable "
            "Neuralese interface without held-out convergence and causal write/reuse tests"
        ),
    }

    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
