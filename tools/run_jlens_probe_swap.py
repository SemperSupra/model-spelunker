#!/usr/bin/env python3
"""Experiment 0002: causal J-space probe-swap calibration on open models.

This is a deliberately narrow reproduction primitive. It consumes Anthropic's
released 90-case two-hop probe-swap set at an immutable upstream commit, uses a
published pre-fitted Jacobian lens, and asks whether replacing the J-space
coordinate of an unspoken intermediate changes the model's next-token answer.

The harness also runs two falsification controls:

* direct-answer swap: swap the clean answer token toward the counterfactual
  answer. This tests whether the intervention apparatus can move the output
  even when the intermediate representation itself is weak.
* norm-matched random perturbation: apply a random perturbation with the same
  per-position norm as the bridge-coordinate swap.

A positive result here is apparatus evidence, not by itself evidence for a
model-independent Neuralese ontology.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch
from huggingface_hub import hf_hub_download, model_info
from transformers import AutoModelForCausalLM, AutoTokenizer

import jlens


JLENS_UPSTREAM_COMMIT = "581d398613e5602a5af361e1c34d3a92ea82ba8e"
PROBE_SWAP_URL = (
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
    parser.add_argument("--dataset-url", default=PROBE_SWAP_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--lens-repo", default=DEFAULT_LENS_REPO)
    parser.add_argument("--lens-revision", default=DEFAULT_LENS_REVISION)
    parser.add_argument("--lens-file", default=DEFAULT_LENS_FILE)
    parser.add_argument("--alphas", default="1,2")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--max-items", type=int, default=90)
    parser.add_argument(
        "--output-dir", default="artifacts/experiment-0002-jlens-probe-swap"
    )
    return parser.parse_args()


def download_json(url: str) -> tuple[dict[str, Any], str]:
    req = urllib.request.Request(url, headers={"User-Agent": "model-spelunker/0002"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def explicit_layout_for(hf_model) -> jlens.Layout | None:
    # Anthropic's pinned adapter predates the Transformers rename from
    # GPT-NeoX ``embed_out`` to ``lm_head``. Keep the compatibility bridge
    # local and explicit rather than patching the pinned upstream package.
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


def token_for_surface(tokenizer, text: str) -> tuple[int, str] | None:
    """Resolve a human surface to one vocabulary token, preferring word-boundary form."""
    candidates = [f" {text}", text]
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ids = tokenizer(candidate, add_special_tokens=False).input_ids
        if len(ids) == 1:
            return int(ids[0]), candidate
    return None


def rank_of(logits: torch.Tensor, token_id: int) -> int:
    target = logits[token_id]
    return int((logits > target).sum().item()) + 1


def decoded(tokenizer, token_id: int) -> str:
    return tokenizer.decode([token_id], skip_special_tokens=False)


def j_vector(model: jlens.HFLensModel, lens: jlens.JacobianLens, layer: int, token_id: int) -> torch.Tensor:
    """Return unit J-lens token direction v_t ~= normalize(J_l^T W_U[t])."""
    J = lens.jacobians[layer].float()
    w = model._lm_head.weight[token_id].detach().float().cpu()
    v = J.T @ w
    return v / v.norm().clamp_min(1e-12)


def deterministic_random_unit(d_model: int, *, seed: int, key: str) -> torch.Tensor:
    digest = hashlib.sha256(f"{seed}|{key}".encode("utf-8")).digest()
    local_seed = int.from_bytes(digest[:8], "big") % (2**63 - 1)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(local_seed)
    v = torch.randn(d_model, generator=generator, dtype=torch.float32)
    return v / v.norm().clamp_min(1e-12)


def coordinate_swap_delta(hidden: torch.Tensor, source: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Compute V(sigma(V^+ h) - V^+ h) for a two-coordinate J-space swap."""
    V = torch.stack((source, target), dim=1).to(hidden.device, torch.float32)  # [d, 2]
    pinv = torch.linalg.pinv(V)  # [2, d]
    h = hidden.float()
    coordinates = h @ pinv.T
    swapped = coordinates.flip(-1)
    return (swapped - coordinates) @ V.T


def run_intervention(
    hf_model,
    model: jlens.HFLensModel,
    lens: jlens.JacobianLens,
    input_ids: torch.Tensor,
    *,
    source_id: int,
    target_id: int,
    alpha: float,
    mode: str,
    seed: int,
    case_name: str,
) -> torch.Tensor:
    """Apply a coordinate swap across all fitted source layers and prompt positions."""
    handles = []
    try:
        for layer in lens.source_layers:
            source = j_vector(model, lens, layer, source_id)
            target = j_vector(model, lens, layer, target_id)
            random_unit = deterministic_random_unit(
                model.d_model, seed=seed, key=f"{case_name}|{layer}|{mode}"
            )

            def hook(_module, _inputs, output, *, source=source, target=target, random_unit=random_unit):
                if isinstance(output, tuple):
                    hidden = output[0]
                else:
                    hidden = output
                raw_delta = coordinate_swap_delta(hidden, source, target)
                if mode == "coordinate_swap":
                    delta = raw_delta
                elif mode == "random_norm_matched":
                    r = random_unit.to(hidden.device, torch.float32)
                    magnitudes = raw_delta.float().norm(dim=-1, keepdim=True)
                    delta = magnitudes * r.view(1, 1, -1)
                else:
                    raise ValueError(f"Unknown intervention mode: {mode}")
                patched = hidden + alpha * delta.to(hidden.device, hidden.dtype)
                if isinstance(output, tuple):
                    return (patched, *output[1:])
                return patched

            handles.append(model.layers[layer].register_forward_hook(hook))

        with torch.inference_mode():
            logits = hf_model(input_ids, use_cache=False).logits[0, -1].detach().float().cpu()
        return logits
    finally:
        for handle in handles:
            handle.remove()


def condition_record(
    *,
    tokenizer,
    logits: torch.Tensor,
    condition: str,
    alpha: float,
    swap_answer_id: int,
    clean_swap_answer_logit: float,
) -> dict[str, Any]:
    predicted_id = int(torch.argmax(logits))
    return {
        "condition": condition,
        "alpha": alpha,
        "predicted_token_id": predicted_id,
        "predicted_token": decoded(tokenizer, predicted_id),
        "swap_answer_rank": rank_of(logits, swap_answer_id),
        "swap_answer_logit": float(logits[swap_answer_id]),
        "swap_answer_logit_delta": float(logits[swap_answer_id]) - clean_swap_answer_logit,
        "swap_answer_top1": predicted_id == swap_answer_id,
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        for result in row["interventions"]:
            grouped[(result["condition"], float(result["alpha"]))].append(result)

    metrics: dict[str, Any] = {}
    for (condition, alpha), rows in sorted(grouped.items()):
        ranks = sorted(int(row["swap_answer_rank"]) for row in rows)
        metrics[f"{condition}@{alpha:g}"] = {
            "n": len(rows),
            "top1_rate": sum(bool(row["swap_answer_top1"]) for row in rows) / max(1, len(rows)),
            "median_swap_answer_rank": ranks[len(ranks) // 2] if ranks else None,
            "mean_swap_answer_logit_delta": (
                sum(float(row["swap_answer_logit_delta"]) for row in rows) / max(1, len(rows))
            ),
        }
    return metrics


def main() -> int:
    args = parse_args()
    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))
    alphas = [float(value) for value in args.alphas.split(",") if value.strip()]
    if not alphas:
        raise ValueError("Need at least one intervention alpha")

    dataset, dataset_sha256 = download_json(args.dataset_url)
    items = list(dataset.get("items", []))[: args.max_items]
    if not items:
        raise ValueError("Probe-swap dataset had no items")

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(f"Could not resolve immutable revision for {args.model}@{args.revision}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    hf_model = AutoModelForCausalLM.from_pretrained(args.model, revision=resolved_revision)
    hf_model.eval().to("cpu")
    explicit_layout = explicit_layout_for(hf_model)
    model = jlens.from_hf(hf_model, tokenizer, layout=explicit_layout)

    lens_path = hf_hub_download(
        repo_id=args.lens_repo,
        filename=args.lens_file,
        revision=args.lens_revision,
    )
    lens = jlens.JacobianLens.load(lens_path)
    if lens.d_model != model.d_model:
        raise ValueError(f"Lens/model d_model mismatch: {lens.d_model} != {model.d_model}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    print(
        f"model={args.model} revision={resolved_revision} lens_layers={lens.source_layers} "
        f"items={len(items)} dataset_sha256={dataset_sha256}"
    )

    for item in items:
        surfaces: dict[str, tuple[int, str] | None] = {
            key: token_for_surface(tokenizer, str(item[key]))
            for key in ("intermediate", "swap_to", "answer", "swap_answer")
        }
        unresolved = [key for key, value in surfaces.items() if value is None]
        if unresolved:
            skipped.append(
                {
                    "name": item["name"],
                    "reason": "multi_token_surface",
                    "unresolved": unresolved,
                }
            )
            continue

        ids = {key: int(value[0]) for key, value in surfaces.items() if value is not None}
        forms = {key: value[1] for key, value in surfaces.items() if value is not None}

        lens_logits, clean_logits_matrix, input_ids = lens.apply(
            model, item["prompt"], positions=[-1]
        )
        clean_logits = clean_logits_matrix[0]
        clean_pred_id = int(torch.argmax(clean_logits))
        clean_correct = clean_pred_id == ids["answer"]

        if not clean_correct:
            skipped.append(
                {
                    "name": item["name"],
                    "reason": "clean_answer_incorrect",
                    "expected_answer": item["answer"],
                    "expected_answer_token": forms["answer"],
                    "predicted_token": decoded(tokenizer, clean_pred_id),
                    "answer_rank": rank_of(clean_logits, ids["answer"]),
                }
            )
            continue

        per_layer_readout = []
        for layer in lens.source_layers:
            logits = lens_logits[layer][0]
            per_layer_readout.append(
                {
                    "layer": layer,
                    "intermediate_rank": rank_of(logits, ids["intermediate"]),
                    "swap_to_rank": rank_of(logits, ids["swap_to"]),
                    "answer_rank": rank_of(logits, ids["answer"]),
                    "swap_answer_rank": rank_of(logits, ids["swap_answer"]),
                }
            )

        clean_swap_answer_logit = float(clean_logits[ids["swap_answer"]])
        interventions: list[dict[str, Any]] = []
        for alpha in alphas:
            bridge_logits = run_intervention(
                hf_model,
                model,
                lens,
                input_ids,
                source_id=ids["intermediate"],
                target_id=ids["swap_to"],
                alpha=alpha,
                mode="coordinate_swap",
                seed=args.seed,
                case_name=item["name"],
            )
            interventions.append(
                condition_record(
                    tokenizer=tokenizer,
                    logits=bridge_logits,
                    condition="bridge_jspace_swap",
                    alpha=alpha,
                    swap_answer_id=ids["swap_answer"],
                    clean_swap_answer_logit=clean_swap_answer_logit,
                )
            )

            answer_logits = run_intervention(
                hf_model,
                model,
                lens,
                input_ids,
                source_id=ids["answer"],
                target_id=ids["swap_answer"],
                alpha=alpha,
                mode="coordinate_swap",
                seed=args.seed,
                case_name=item["name"],
            )
            interventions.append(
                condition_record(
                    tokenizer=tokenizer,
                    logits=answer_logits,
                    condition="direct_answer_jspace_swap",
                    alpha=alpha,
                    swap_answer_id=ids["swap_answer"],
                    clean_swap_answer_logit=clean_swap_answer_logit,
                )
            )

            random_logits = run_intervention(
                hf_model,
                model,
                lens,
                input_ids,
                source_id=ids["intermediate"],
                target_id=ids["swap_to"],
                alpha=alpha,
                mode="random_norm_matched",
                seed=args.seed,
                case_name=item["name"],
            )
            interventions.append(
                condition_record(
                    tokenizer=tokenizer,
                    logits=random_logits,
                    condition="random_norm_matched",
                    alpha=alpha,
                    swap_answer_id=ids["swap_answer"],
                    clean_swap_answer_logit=clean_swap_answer_logit,
                )
            )

        record = {
            "name": item["name"],
            "category": item["category"],
            "prompt": item["prompt"],
            "intermediate": item["intermediate"],
            "swap_to": item["swap_to"],
            "answer": item["answer"],
            "swap_answer": item["swap_answer"],
            "token_forms": forms,
            "token_ids": ids,
            "input_tokens": int(input_ids.shape[-1]),
            "clean_predicted_token": decoded(tokenizer, clean_pred_id),
            "clean_answer_rank": rank_of(clean_logits, ids["answer"]),
            "clean_swap_answer_rank": rank_of(clean_logits, ids["swap_answer"]),
            "best_intermediate_readout_rank": min(
                row["intermediate_rank"] for row in per_layer_readout
            ),
            "per_layer_readout": per_layer_readout,
            "interventions": interventions,
        }
        records.append(record)
        print(
            json.dumps(
                {
                    "name": record["name"],
                    "category": record["category"],
                    "best_intermediate_readout_rank": record["best_intermediate_readout_rank"],
                    "interventions": [
                        {
                            "condition": row["condition"],
                            "alpha": row["alpha"],
                            "swap_answer_rank": row["swap_answer_rank"],
                            "swap_answer_top1": row["swap_answer_top1"],
                        }
                        for row in interventions
                    ],
                },
                ensure_ascii=False,
            )
        )

    metrics = aggregate(records)
    summary = {
        "experiment": "0002-jlens-probe-swap-causal-calibration",
        "model": args.model,
        "model_class": hf_model.__class__.__name__,
        "requested_revision": args.revision,
        "resolved_model_revision": resolved_revision,
        "jlens_upstream_commit": JLENS_UPSTREAM_COMMIT,
        "dataset_url": args.dataset_url,
        "dataset_sha256": dataset_sha256,
        "released_item_count_considered": len(items),
        "evaluated_clean_correct_single_token_items": len(records),
        "skipped_items": len(skipped),
        "lens_repo": args.lens_repo,
        "lens_revision": args.lens_revision,
        "lens_file": args.lens_file,
        "lens_n_prompts": lens.n_prompts,
        "lens_source_layers": lens.source_layers,
        "alphas": alphas,
        "controls": ["direct_answer_jspace_swap", "random_norm_matched"],
        "metrics": metrics,
        "promotion_note": (
            "This is a causal calibration rep. Bridge-swap success above the random control "
            "with a functioning direct-answer control earns a stronger held-out/subspace and "
            "cross-language rep; it does not by itself establish addressable Neuralese."
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

    # The run is still valid if a tiny plumbing model has few eligible cases; that
    # outcome tells us whether to promote the apparatus to a stronger open model.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
