#!/usr/bin/env python3
"""Experiment 0002: minimal external-to-latent read/write smoke test.

This is a plumbing/falsification harness, not a claim that a single direction is the
model's true concept representation. It derives a candidate P-vs-N direction from
training probes, evaluates held-out readout, then performs a causal write test by
adding the direction at one transformer layer and comparing the change in semantic
continuation preference against a norm-matched random direction.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch
from huggingface_hub import model_info
from transformers import AutoModelForCausalLM, AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--train-fixture",
        default="fixtures/experiment-0001/reciprocity-semantic-smoke.jsonl",
    )
    parser.add_argument(
        "--heldout-fixture",
        default="fixtures/experiment-0001/reciprocity-semantic-heldout.jsonl",
    )
    parser.add_argument("--model", default="EleutherAI/pythia-70m")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--output-dir", default="artifacts/experiment-0002-latent-interface")
    parser.add_argument(
        "--alphas",
        default="-1,-0.5,0,0.5,1",
        help="Comma-separated multiples of the learned mean-difference direction.",
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def labeled_pn(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("expected") in {"positive", "negative"}]


def capture_last_token_states(model, tokenizer, prompt: str) -> list[torch.Tensor]:
    ids = tokenizer(prompt, add_special_tokens=False, return_tensors="pt").input_ids
    with torch.inference_mode():
        out = model(ids, output_hidden_states=True, use_cache=False)
    # hidden_states[0] is embedding output; hidden_states[i+1] is layer i output.
    return [state[0, -1].detach().cpu().float() for state in out.hidden_states[1:]]


def accuracy(rows: list[dict[str, Any]], vectors: list[list[torch.Tensor]], layer: int,
             direction: torch.Tensor, midpoint: torch.Tensor) -> tuple[float, list[dict[str, Any]]]:
    unit = direction / direction.norm().clamp_min(1e-12)
    results: list[dict[str, Any]] = []
    correct = 0
    for row, per_layer in zip(rows, vectors):
        projection = float(torch.dot(per_layer[layer] - midpoint, unit))
        selected = "positive" if projection >= 0 else "negative"
        expected = row["expected"]
        correct += int(selected == expected)
        results.append(
            {
                "surface_id": row["surface_id"],
                "language": row["language"],
                "expected": expected,
                "selected": selected,
                "projection": projection,
            }
        )
    return correct / max(1, len(rows)), results


def derive_layer_stats(train_rows, train_vectors, heldout_rows, heldout_vectors):
    num_layers = len(train_vectors[0])
    per_layer: list[dict[str, Any]] = []
    learned: list[tuple[torch.Tensor, torch.Tensor]] = []

    for layer in range(num_layers):
        pos = [vecs[layer] for row, vecs in zip(train_rows, train_vectors) if row["expected"] == "positive"]
        neg = [vecs[layer] for row, vecs in zip(train_rows, train_vectors) if row["expected"] == "negative"]
        p_mean = torch.stack(pos).mean(dim=0)
        n_mean = torch.stack(neg).mean(dim=0)
        direction = p_mean - n_mean
        midpoint = (p_mean + n_mean) / 2.0
        train_acc, _ = accuracy(train_rows, train_vectors, layer, direction, midpoint)
        heldout_acc, heldout_detail = accuracy(
            heldout_rows, heldout_vectors, layer, direction, midpoint
        )
        unit = direction / direction.norm().clamp_min(1e-12)
        projections = [
            float(torch.dot(vecs[layer] - midpoint, unit)) for vecs in train_vectors
        ]
        mean_abs_projection = sum(abs(x) for x in projections) / max(1, len(projections))
        per_layer.append(
            {
                "layer": layer,
                "direction_norm": float(direction.norm()),
                "train_accuracy": train_acc,
                "heldout_accuracy": heldout_acc,
                "train_mean_abs_projection": mean_abs_projection,
                "heldout": heldout_detail,
            }
        )
        learned.append((direction, midpoint))

    # Layer selection uses training data only. Held-out accuracy is never used to select.
    chosen = max(
        per_layer,
        key=lambda row: (row["train_accuracy"], row["train_mean_abs_projection"]),
    )["layer"]
    return per_layer, learned, chosen


def conditional_mean_logprob_with_delta(
    model,
    tokenizer,
    prompt: str,
    continuation: str,
    layer: int,
    delta: torch.Tensor,
) -> float:
    prompt_ids = tokenizer(prompt, add_special_tokens=False, return_tensors="pt").input_ids
    full_ids = tokenizer(prompt + continuation, add_special_tokens=False, return_tensors="pt").input_ids
    prompt_len = prompt_ids.shape[1]
    full_len = full_ids.shape[1]
    if full_len <= prompt_len:
        raise ValueError("Continuation added no tokens")
    if not torch.equal(full_ids[:, :prompt_len], prompt_ids):
        raise ValueError("Prompt/continuation tokenization boundary is not prefix-stable")

    layers = getattr(getattr(model, "gpt_neox", None), "layers", None)
    if layers is None:
        raise RuntimeError(
            "Experiment 0002 smoke intervention currently supports GPT-NeoX/Pythia models; "
            "generalize the layer adapter before changing model families."
        )

    target_pos = prompt_len - 1
    delta_cpu = delta.detach().cpu()

    def hook(_module, _inputs, output):
        if isinstance(output, tuple):
            hidden = output[0].clone()
            hidden[:, target_pos, :] += delta_cpu.to(hidden.device, hidden.dtype)
            return (hidden, *output[1:])
        hidden = output.clone()
        hidden[:, target_pos, :] += delta_cpu.to(hidden.device, hidden.dtype)
        return hidden

    handle = layers[layer].register_forward_hook(hook)
    try:
        with torch.inference_mode():
            logits = model(full_ids, use_cache=False).logits
            log_probs = torch.log_softmax(logits, dim=-1)
    finally:
        handle.remove()

    token_logps: list[float] = []
    for token_position in range(prompt_len, full_len):
        prediction_position = token_position - 1
        target_id = int(full_ids[0, token_position])
        token_logps.append(float(log_probs[0, prediction_position, target_id]))
    return sum(token_logps) / len(token_logps)


def semantic_margin(model, tokenizer, probe, layer: int, delta: torch.Tensor) -> float:
    pos = conditional_mean_logprob_with_delta(
        model, tokenizer, probe["prompt"], probe["positive_continuation"], layer, delta
    )
    neg = conditional_mean_logprob_with_delta(
        model, tokenizer, probe["prompt"], probe["negative_continuation"], layer, delta
    )
    return pos - neg


def choose_intervention_probes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("expected") == "negative":
            by_language[row["language"]].append(row)
    selected: list[dict[str, Any]] = []
    for language in sorted(by_language):
        selected.append(sorted(by_language[language], key=lambda row: row["surface_id"])[0])
    return selected


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))
    alphas = [float(value) for value in args.alphas.split(",") if value.strip()]
    if 0.0 not in alphas:
        raise ValueError("--alphas must include 0 for a baseline")

    train_rows = labeled_pn(read_jsonl(Path(args.train_fixture)))
    heldout_rows = labeled_pn(read_jsonl(Path(args.heldout_fixture)))
    if not train_rows or not heldout_rows:
        raise ValueError("Need labeled positive/negative train and held-out probes")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(f"Could not resolve immutable revision for {args.model}@{args.revision}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=resolved_revision)
    model.eval()
    model.to("cpu")

    print(f"capturing train={len(train_rows)} heldout={len(heldout_rows)}")
    train_vectors = [capture_last_token_states(model, tokenizer, row["prompt"]) for row in train_rows]
    heldout_vectors = [
        capture_last_token_states(model, tokenizer, row["prompt"]) for row in heldout_rows
    ]

    per_layer, learned, chosen_layer = derive_layer_stats(
        train_rows, train_vectors, heldout_rows, heldout_vectors
    )
    direction, _midpoint = learned[chosen_layer]

    generator = torch.Generator(device="cpu")
    generator.manual_seed(args.seed + 1)
    random_direction = torch.randn(direction.shape, generator=generator, dtype=direction.dtype)
    random_direction = random_direction / random_direction.norm().clamp_min(1e-12)
    random_direction = random_direction * direction.norm()

    intervention_rows: list[dict[str, Any]] = []
    probes = choose_intervention_probes(heldout_rows)
    for probe in probes:
        for direction_name, base_direction in (
            ("concept", direction),
            ("random", random_direction),
        ):
            baseline_margin = None
            margins: dict[str, float] = {}
            for alpha in alphas:
                delta = base_direction * alpha
                margin = semantic_margin(model, tokenizer, probe, chosen_layer, delta)
                margins[str(alpha)] = margin
                if alpha == 0.0:
                    baseline_margin = margin
            assert baseline_margin is not None
            for alpha in alphas:
                margin = margins[str(alpha)]
                row = {
                    "surface_id": probe["surface_id"],
                    "probe_id": probe["probe_id"],
                    "language": probe["language"],
                    "layer": chosen_layer,
                    "direction": direction_name,
                    "alpha": alpha,
                    "margin": margin,
                    "delta_from_baseline": margin - baseline_margin,
                }
                intervention_rows.append(row)
                print(json.dumps(row, ensure_ascii=False))

    concept_positive_deltas = [
        row["delta_from_baseline"]
        for row in intervention_rows
        if row["direction"] == "concept" and row["alpha"] > 0
    ]
    random_positive_deltas = [
        row["delta_from_baseline"]
        for row in intervention_rows
        if row["direction"] == "random" and row["alpha"] > 0
    ]

    summary = {
        "experiment": "0002-external-to-latent-interface-discovery",
        "model": args.model,
        "requested_revision": args.revision,
        "resolved_revision": resolved_revision,
        "train_fixture": args.train_fixture,
        "heldout_fixture": args.heldout_fixture,
        "train_probe_count": len(train_rows),
        "heldout_probe_count": len(heldout_rows),
        "chosen_layer": chosen_layer,
        "chosen_train_accuracy": per_layer[chosen_layer]["train_accuracy"],
        "chosen_heldout_accuracy": per_layer[chosen_layer]["heldout_accuracy"],
        "direction_norm": float(direction.norm()),
        "intervention_probe_count": len(probes),
        "alphas": alphas,
        "mean_positive_alpha_concept_delta": (
            sum(concept_positive_deltas) / max(1, len(concept_positive_deltas))
        ),
        "mean_positive_alpha_random_delta": (
            sum(random_positive_deltas) / max(1, len(random_positive_deltas))
        ),
        "interpretation": (
            "plumbing-only; a single P-vs-N direction is a candidate observer/intervention, "
            "not an assumed neuralese ontology"
        ),
    }

    (out_dir / "layer-readout.json").write_text(
        json.dumps(per_layer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (out_dir / "interventions.jsonl").open("w", encoding="utf-8") as handle:
        for row in intervention_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
