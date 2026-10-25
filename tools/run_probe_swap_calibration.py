#!/usr/bin/env python3
"""Run a small, reproducible causal J-space probe-swap calibration.

The primary intervention follows Anthropic's released probe-swap demonstration:
for each selected layer, construct the two J-lens token directions, project the
residual into their 2-D span, exchange the two coordinates, and reconstruct only
that in-span delta.  The prompt itself is unchanged.

This harness intentionally separates:
- paper-faithful causal evidence: clean top-1 answer -> swapped top-1 answer;
- weaker but useful preference flips: answer logit > swap-answer logit becomes
  swap-answer logit > answer logit;
- layer-band ablations and strength sweeps.

It is a calibration primitive, not evidence that a general Neuralese ontology
has been discovered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import torch
from huggingface_hub import hf_hub_download, model_info
from transformers import AutoModelForCausalLM, AutoTokenizer

import jlens


JLENS_UPSTREAM_COMMIT = "581d398613e5602a5af361e1c34d3a92ea82ba8e"
DEFAULT_DATA_URL = (
    "https://raw.githubusercontent.com/anthropics/jacobian-lens/"
    f"{JLENS_UPSTREAM_COMMIT}/data/experiments/probe-swap.json"
)
DEFAULT_MODEL = "EleutherAI/pythia-70m-deduped"
DEFAULT_LENS_REPO = "neuronpedia/jacobian-lens"
DEFAULT_LENS_REVISION = "91271eb5b15a43eebed7bb447618738754f1379a"
DEFAULT_LENS_FILE = (
    "pythia-70m-deduped/jlens/Salesforce-wikitext/"
    "pythia-70m-deduped_jacobian_lens.pt"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--lens-repo", default=DEFAULT_LENS_REPO)
    parser.add_argument("--lens-revision", default=DEFAULT_LENS_REVISION)
    parser.add_argument("--lens-file", default=DEFAULT_LENS_FILE)
    parser.add_argument("--data-url", default=DEFAULT_DATA_URL)
    parser.add_argument("--strengths", default="0.5,1.0,2.0")
    parser.add_argument("--max-items", type=int, default=90)
    parser.add_argument(
        "--output-dir", default="artifacts/experiment-0002-probe-swap-calibration"
    )
    return parser.parse_args()


def fetch_json(url: str) -> tuple[dict[str, Any], str]:
    request = urllib.request.Request(url, headers={"User-Agent": "model-spelunker/0002"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    return json.loads(payload.decode("utf-8")), digest


def explicit_layout_for(hf_model) -> jlens.Layout | None:
    """Bridge the known GPT-NeoX unembedding rename without patching upstream."""
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


def token_variants(tokenizer, word: str) -> list[int]:
    """Return unique single-token variants, preferring ordinary leading-space form."""
    ids: list[int] = []
    for candidate in (" " + word, word):
        encoded = tokenizer.encode(candidate, add_special_tokens=False)
        if len(encoded) == 1 and encoded[0] not in ids:
            ids.append(int(encoded[0]))
    return ids


def preferred_token_id(tokenizer, word: str) -> int | None:
    variants = token_variants(tokenizer, word)
    return variants[0] if variants else None


def min_rank(logits: torch.Tensor, token_ids: Iterable[int]) -> int | None:
    ranks = [int((logits > logits[token_id]).sum().item()) + 1 for token_id in token_ids]
    return min(ranks) if ranks else None


def max_logit(logits: torch.Tensor, token_ids: Iterable[int]) -> float | None:
    values = [float(logits[token_id].item()) for token_id in token_ids]
    return max(values) if values else None


def _replace_hidden(output, hidden):
    if torch.is_tensor(output):
        return hidden
    if isinstance(output, tuple):
        return (hidden, *output[1:])
    if isinstance(output, list):
        return [hidden, *output[1:]]
    raise TypeError(f"Unsupported block output type: {type(output)!r}")


@contextmanager
def lens_coordinate_swap(
    model,
    lens,
    source_id: int,
    target_id: int,
    layers: Iterable[int],
    *,
    strength: float = 1.0,
):
    """Exchange two J-lens coordinates, leaving the orthogonal residual untouched.

    For each selected layer l:
      V = [J_l^T w_source, J_l^T w_target]
      c = V^+ h
      h' = h + strength * V * ([c_target, c_source] - c)

    The hook applies to every prompt position, matching the released demo.
    """
    layers = list(layers)
    unembedding_rows = model._lm_head.weight[[source_id, target_id]].float().cpu()
    layer_bases: dict[int, tuple[torch.Tensor, torch.Tensor]] = {}

    for layer in layers:
        jacobian = lens.jacobians[layer].float().cpu()
        source_direction = jacobian.T @ unembedding_rows[0]
        target_direction = jacobian.T @ unembedding_rows[1]
        basis = torch.stack([source_direction, target_direction], dim=1)
        layer_bases[layer] = (basis, torch.linalg.pinv(basis))

    handles = []
    try:
        for layer in layers:
            basis_cpu, pinv_cpu = layer_bases[layer]

            def hook(
                _module,
                _inputs,
                output,
                basis_cpu=basis_cpu,
                pinv_cpu=pinv_cpu,
            ):
                hidden = output if torch.is_tensor(output) else output[0]
                basis = basis_cpu.to(hidden.device)
                pinv = pinv_cpu.to(hidden.device)
                hidden_fp32 = hidden.float()
                coordinates = hidden_fp32 @ pinv.T
                swapped = coordinates.flip(-1)
                patched = hidden_fp32 + strength * ((swapped - coordinates) @ basis.T)
                return _replace_hidden(output, patched.to(hidden.dtype))

            handles.append(model.layers[layer].register_forward_hook(hook))
        yield
    finally:
        for handle in handles:
            handle.remove()


def split_bands(source_layers: list[int]) -> dict[str, list[int]]:
    """Return an apparatus band plus simple early/late ablation controls.

    'all_fitted' is the primary calibration because no Pythia-specific workspace
    band is assumed.  early/late halves are explicitly ablations, not claims of
    a discovered workspace boundary.
    """
    if not source_layers:
        raise ValueError("Lens has no source layers")
    midpoint = max(1, len(source_layers) // 2)
    bands = {"all_fitted": source_layers}
    if len(source_layers) >= 2:
        bands["early_half"] = source_layers[:midpoint]
        bands["late_half"] = source_layers[midpoint:]
    return bands


def main() -> int:
    args = parse_args()
    strengths = [float(value) for value in args.strengths.split(",") if value.strip()]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    experiment, data_sha256 = fetch_json(args.data_url)
    items = experiment["items"][: args.max_items]

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(f"Could not resolve immutable model revision for {args.model}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    hf_model = AutoModelForCausalLM.from_pretrained(args.model, revision=resolved_revision)
    hf_model.eval().to("cpu")
    layout = explicit_layout_for(hf_model)
    model = jlens.from_hf(hf_model, tokenizer, layout=layout)

    lens_path = hf_hub_download(
        repo_id=args.lens_repo,
        filename=args.lens_file,
        revision=args.lens_revision,
    )
    lens = jlens.JacobianLens.load(lens_path)
    if lens.d_model != model.d_model:
        raise ValueError(f"Lens/model width mismatch: {lens.d_model} != {model.d_model}")

    bands = split_bands(list(lens.source_layers))
    primary_band = bands["all_fitted"]

    @torch.no_grad()
    def next_token_logits(prompt: str) -> torch.Tensor:
        input_ids = tokenizer(prompt, return_tensors="pt").input_ids.to(model.input_device)
        return hf_model(input_ids=input_ids, use_cache=False).logits[0, -1].float().cpu()

    rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}

    for index, item in enumerate(items):
        source_id = preferred_token_id(tokenizer, item["intermediate"])
        target_id = preferred_token_id(tokenizer, item["swap_to"])
        answer_ids = token_variants(tokenizer, item["answer"])
        swap_answer_ids = token_variants(tokenizer, item["swap_answer"])

        if source_id is None or target_id is None or not answer_ids or not swap_answer_ids:
            reason = "non_single_token_required_field"
            skipped[reason] = skipped.get(reason, 0) + 1
            rows.append(
                {
                    "name": item["name"],
                    "category": item["category"],
                    "skipped": True,
                    "skip_reason": reason,
                }
            )
            continue

        clean = next_token_logits(item["prompt"])
        clean_top = int(clean.argmax().item())
        answer_logit = max_logit(clean, answer_ids)
        swap_logit = max_logit(clean, swap_answer_ids)
        assert answer_logit is not None and swap_logit is not None
        baseline_greedy_correct = clean_top in answer_ids
        baseline_prefers_answer = answer_logit > swap_logit

        row: dict[str, Any] = {
            "name": item["name"],
            "category": item["category"],
            "prompt": item["prompt"],
            "intermediate": item["intermediate"],
            "swap_to": item["swap_to"],
            "answer": item["answer"],
            "swap_answer": item["swap_answer"],
            "source_token_id": source_id,
            "target_token_id": target_id,
            "answer_token_ids": answer_ids,
            "swap_answer_token_ids": swap_answer_ids,
            "baseline": {
                "top_token_id": clean_top,
                "top_token": tokenizer.decode([clean_top]),
                "greedy_correct": baseline_greedy_correct,
                "prefers_answer": baseline_prefers_answer,
                "answer_rank": min_rank(clean, answer_ids),
                "swap_answer_rank": min_rank(clean, swap_answer_ids),
                "answer_minus_swap_logit": answer_logit - swap_logit,
            },
            "conditions": {},
        }

        condition_specs: list[tuple[str, list[int], float]] = []
        for strength in strengths:
            condition_specs.append((f"all_fitted@s{strength:g}", primary_band, strength))
        for band_name in ("early_half", "late_half"):
            if band_name in bands:
                condition_specs.append((f"{band_name}@s1", bands[band_name], 1.0))

        for condition_name, layers, strength in condition_specs:
            with lens_coordinate_swap(
                model,
                lens,
                source_id,
                target_id,
                layers,
                strength=strength,
            ):
                swapped_logits = next_token_logits(item["prompt"])

            top_id = int(swapped_logits.argmax().item())
            post_answer_logit = max_logit(swapped_logits, answer_ids)
            post_swap_logit = max_logit(swapped_logits, swap_answer_ids)
            assert post_answer_logit is not None and post_swap_logit is not None
            prefers_swap = post_swap_logit > post_answer_logit
            greedy_swap = top_id in swap_answer_ids
            row["conditions"][condition_name] = {
                "layers": layers,
                "strength": strength,
                "top_token_id": top_id,
                "top_token": tokenizer.decode([top_id]),
                "greedy_swap_answer": greedy_swap,
                "causal_success": baseline_greedy_correct and greedy_swap,
                "prefers_swap_answer": prefers_swap,
                "preference_flip": baseline_prefers_answer and prefers_swap,
                "answer_rank": min_rank(swapped_logits, answer_ids),
                "swap_answer_rank": min_rank(swapped_logits, swap_answer_ids),
                "answer_minus_swap_logit": post_answer_logit - post_swap_logit,
                "margin_change": (post_answer_logit - post_swap_logit)
                - (answer_logit - swap_logit),
            }

        rows.append(row)
        if (index + 1) % 15 == 0:
            print(f"progress {index + 1}/{len(items)}", flush=True)

    scored = [row for row in rows if not row.get("skipped")]
    baseline_greedy = [row for row in scored if row["baseline"]["greedy_correct"]]
    baseline_pref = [row for row in scored if row["baseline"]["prefers_answer"]]

    condition_names = sorted(
        {name for row in scored for name in row.get("conditions", {}).keys()}
    )
    condition_summary: dict[str, Any] = {}
    for name in condition_names:
        values = [row["conditions"][name] for row in scored]
        causal_count = sum(value["causal_success"] for value in values)
        pref_flip_count = sum(value["preference_flip"] for value in values)
        greedy_swap_count = sum(value["greedy_swap_answer"] for value in values)
        condition_summary[name] = {
            "greedy_swap_answer_count": greedy_swap_count,
            "greedy_swap_answer_rate_scored": greedy_swap_count / len(scored) if scored else 0.0,
            "causal_success_count": causal_count,
            "causal_success_rate_given_clean_greedy_correct": (
                causal_count / len(baseline_greedy) if baseline_greedy else 0.0
            ),
            "preference_flip_count": pref_flip_count,
            "preference_flip_rate_given_clean_prefers_answer": (
                pref_flip_count / len(baseline_pref) if baseline_pref else 0.0
            ),
            "mean_margin_change": (
                sum(value["margin_change"] for value in values) / len(values)
                if values
                else 0.0
            ),
        }

    summary = {
        "experiment": "0002-jspace-probe-swap-calibration",
        "method": "released two-coordinate J-lens swap; all_fitted primary with early/late ablations",
        "model": args.model,
        "model_class": hf_model.__class__.__name__,
        "resolved_model_revision": resolved_revision,
        "jlens_upstream_commit": JLENS_UPSTREAM_COMMIT,
        "lens_repo": args.lens_repo,
        "lens_revision": args.lens_revision,
        "lens_file": args.lens_file,
        "lens_n_prompts": lens.n_prompts,
        "lens_source_layers": list(lens.source_layers),
        "bands": bands,
        "strengths": strengths,
        "probe_swap_data_url": args.data_url,
        "probe_swap_data_sha256": data_sha256,
        "published_item_count": len(experiment["items"]),
        "requested_item_count": len(items),
        "scored_item_count": len(scored),
        "skipped": skipped,
        "baseline_greedy_correct_count": len(baseline_greedy),
        "baseline_greedy_correct_rate": len(baseline_greedy) / len(scored) if scored else 0.0,
        "baseline_prefers_answer_count": len(baseline_pref),
        "baseline_prefers_answer_rate": len(baseline_pref) / len(scored) if scored else 0.0,
        "conditions": condition_summary,
        "interpretation": (
            "Calibration only. Promotion requires reproducible causal swaps with layer/strength "
            "specificity and later cross-language/task-reuse tests; a preference flip alone is "
            "weaker evidence than a clean-answer to counterfactual-answer top-1 flip."
        ),
    }

    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
