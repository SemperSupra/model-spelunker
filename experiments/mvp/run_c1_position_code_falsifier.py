#!/usr/bin/env python3
"""Rep 36: causal position-code falsifier for the learned reverse specimen.

Train the frozen seed-0 reverse model exactly as in Rep 34/35, then intervene only
on its learned absolute position-embedding table. For fixed permutations P of the
four content-position codes, the predeclared routing prediction is the conjugate
P^-1 r P of the reverse permutation r. This tests whether the observed learned
attention route is causally tied to the position code rather than merely correlated
with successful behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Any

import haiku as hk
import jax
import jax.numpy as jnp
import numpy as np

from experiments.mvp import run_c1_learned_reverse as base

PRIOR_SEED0_FINAL_HASHES = {
    "rep34": "sha256:33d9f23ac17c89c6f37340d0ebb864f48bc164622b602ccea6d68ff7a9d41040",
    "rep35": "sha256:3567ca98f5bac6b934aef29319a4b21dccf5c4369a55b0ee8784343c4d5b53a2",
}

PERMUTATIONS = {
    "identity": [0, 1, 2, 3, 4],
    "cycle_content_plus1": [0, 2, 3, 4, 1],
    "swap_content_1_2": [0, 2, 1, 3, 4],
}


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def inverse_perm(p: list[int]) -> list[int]:
    inv = [0] * len(p)
    for physical, semantic in enumerate(p):
        inv[semantic] = physical
    return inv


def conjugate_route(p: list[int]) -> list[int]:
    inv = inverse_perm(p)
    r = base.TARGET_ROUTE
    return [inv[r[p[q]]] for q in range(base.SEQ_LEN)]


def find_position_table(params: hk.Params) -> tuple[str, str, np.ndarray]:
    d = hk.data_structures.to_mutable_dict(params)
    matches = []
    for module, leaves in d.items():
        for name, value in leaves.items():
            arr = np.asarray(value)
            if name == "position_embeddings" and arr.shape == (base.SEQ_LEN, base.MODEL_DIM):
                matches.append((module, name, arr))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one position table, found {[(m,n,a.shape) for m,n,a in matches]}")
    return matches[0]


def replace_position_table(params: hk.Params, table: np.ndarray) -> hk.Params:
    d = hk.data_structures.to_mutable_dict(params)
    module, name, original = find_position_table(params)
    if table.shape != original.shape:
        raise RuntimeError(f"position table shape mismatch: {table.shape} vs {original.shape}")
    d[module][name] = jnp.asarray(table, dtype=original.dtype)
    return hk.data_structures.to_immutable_dict(d)


def permute_position_codes(params: hk.Params, p: list[int]) -> hk.Params:
    _, _, table = find_position_table(params)
    return replace_position_table(params, table[np.asarray(p, dtype=np.int64)])


def collapse_content_positions(params: hk.Params) -> hk.Params:
    _, _, table = find_position_table(params)
    out = np.array(table, copy=True)
    out[1:] = np.mean(table[1:], axis=0, keepdims=True)
    return replace_position_table(params, out)


def predictions(params: hk.Params, x: np.ndarray) -> np.ndarray:
    logits, _ = base.TRANSFORMED.apply(params, jnp.asarray(x))
    return np.asarray(jnp.argmax(logits, axis=-1), dtype=np.int32)


def sequence_accuracy_to_target(pred: np.ndarray, target: np.ndarray) -> float:
    return float(np.mean(np.all(pred == target, axis=-1)))


def route_metrics_for(attn_logits: list[np.ndarray], target_route: list[int]) -> list[dict[str, Any]]:
    rows = []
    target = np.asarray(target_route, dtype=np.int64)
    for layer, raw in enumerate(attn_logits):
        a = base.attention_to_bhqk(raw)
        shifted = a - np.max(a, axis=-1, keepdims=True)
        probs = np.exp(shifted)
        probs /= np.sum(probs, axis=-1, keepdims=True)
        target_probs = np.stack([probs[:, 0, q, target[q]] for q in range(1, base.SEQ_LEN)], axis=1)
        argmax = np.argmax(a[:, 0], axis=-1)
        content_argmax = argmax[:, 1:]
        target_content = target[None, 1:]
        entropy = -np.sum(probs[:, 0, 1:, :] * np.log(np.maximum(probs[:, 0, 1:, :], 1e-30)), axis=-1)
        rows.append({
            "layer": layer,
            "mean_target_route_probability_content": float(np.mean(target_probs)),
            "target_route_argmax_fraction_content": float(np.mean(content_argmax == target_content)),
            "mean_content_attention_entropy": float(np.mean(entropy)),
            "mean_attention_matrix": np.mean(probs[:, 0], axis=0).astype(float).tolist(),
        })
    return rows


def evaluate(params: hk.Params, x: np.ndarray, original_target: np.ndarray, predicted_route: list[int] | None) -> dict[str, Any]:
    pred = predictions(params, x)
    outputs = base.stack_learned_outputs(params, x)
    original_routes = route_metrics_for(outputs["attn_logits"], base.TARGET_ROUTE)
    row: dict[str, Any] = {
        "parameter_sha256": base.params_hash(params)[0],
        "original_reverse_sequence_accuracy": sequence_accuracy_to_target(pred, original_target),
        "original_reverse_route": original_routes,
        "prediction_sha256": base.array_hash(pred),
    }
    if predicted_route is not None:
        target = np.asarray(x[:, predicted_route], dtype=np.int32)
        predicted_routes = route_metrics_for(outputs["attn_logits"], predicted_route)
        row.update({
            "predicted_route": predicted_route,
            "predicted_route_sequence_accuracy": sequence_accuracy_to_target(pred, target),
            "predicted_route_attention": predicted_routes,
            "best_predicted_route_probability": max(x["mean_target_route_probability_content"] for x in predicted_routes),
            "best_predicted_route_argmax_fraction": max(x["target_route_argmax_fraction_content"] for x in predicted_routes),
            "best_original_route_probability": max(x["mean_target_route_probability_content"] for x in original_routes),
            "best_original_route_argmax_fraction": max(x["target_route_argmax_fraction_content"] for x in original_routes),
        })
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/c1-position-code-falsifier.json"))
    args = ap.parse_args()

    started = time.perf_counter()
    split = base.make_split()
    train_start = time.perf_counter()
    final_params, _ = base.train_once(split, capture=False)
    training_seconds = time.perf_counter() - train_start
    final_hash, final_count = base.params_hash(final_params)
    baseline_acc = base.accuracy(final_params, split["test_x"], split["test_y"])
    if baseline_acc["sequence_accuracy"] < 0.99:
        raise RuntimeError(f"learned specimen did not reach prerequisite behavior: {baseline_acc}")

    module, name, table = find_position_table(final_params)
    interventions = []
    for intervention_id, p in PERMUTATIONS.items():
        predicted_route = conjugate_route(p)
        altered = permute_position_codes(final_params, p)
        interventions.append({
            "id": intervention_id,
            "kind": "position_code_permutation",
            "position_code_permutation_physical_to_original_semantic": p,
            "predeclared_predicted_route": predicted_route,
            "evaluation": evaluate(altered, split["test_x"], split["test_y"], predicted_route),
        })

    collapsed = collapse_content_positions(final_params)
    collapse_eval = evaluate(collapsed, split["test_x"], split["test_y"], None)
    collapse_eval["best_original_route_probability"] = max(
        x["mean_target_route_probability_content"] for x in collapse_eval["original_reverse_route"]
    )
    collapse_eval["best_original_route_argmax_fraction"] = max(
        x["target_route_argmax_fraction_content"] for x in collapse_eval["original_reverse_route"]
    )
    interventions.append({
        "id": "collapse_content_position_codes",
        "kind": "position_code_collapse_control",
        "position_code_permutation_physical_to_original_semantic": None,
        "predeclared_predicted_route": None,
        "evaluation": collapse_eval,
    })

    by_id = {x["id"]: x for x in interventions}
    identity_eval = by_id["identity"]["evaluation"]
    structured = [by_id["cycle_content_plus1"], by_id["swap_content_1_2"]]
    structured_prediction_wins = []
    structured_behavior = []
    for row in structured:
        ev = row["evaluation"]
        structured_prediction_wins.append(ev["best_predicted_route_probability"] > ev["best_original_route_probability"])
        structured_behavior.append(ev["predicted_route_sequence_accuracy"])

    observations = {
        "learned_specimen": {
            "task": "reverse length-4 content over vocabulary {1,2,3}",
            "seed": base.SEED,
            "training_steps": base.STEPS,
            "architecture": {
                "implementation": "tracr.transformer.model.Transformer",
                "model_dim": base.MODEL_DIM,
                "num_layers": base.NUM_LAYERS,
                "num_heads": base.NUM_HEADS,
                "key_size": base.KEY_SIZE,
            },
            "final_parameter_sha256": final_hash,
            "final_parameter_count": final_count,
            "position_table_module": module,
            "position_table_name": name,
            "position_table_shape": list(table.shape),
            "baseline_test_accuracy": baseline_acc,
        },
        "causal_protocol": {
            "original_reverse_route": base.TARGET_ROUTE,
            "permutation_semantics": "new_position_table[q] = old_position_table[P[q]]",
            "predeclared_route_prediction": "P^-1 o reverse o P",
            "interventions": interventions,
        },
        "cross_job_reproducibility_context": {
            "prior_seed0_final_parameter_sha256": PRIOR_SEED0_FINAL_HASHES,
            "current_seed0_final_parameter_sha256": final_hash,
            "current_matches_rep34": final_hash == PRIOR_SEED0_FINAL_HASHES["rep34"],
            "current_matches_rep35": final_hash == PRIOR_SEED0_FINAL_HASHES["rep35"],
        },
    }

    derived = {
        "identity_parameter_hash_equal_to_baseline": identity_eval["parameter_sha256"] == final_hash,
        "identity_original_reverse_sequence_accuracy": identity_eval["original_reverse_sequence_accuracy"],
        "identity_best_original_route_probability": identity_eval["best_original_route_probability"],
        "structured_permutation_predicted_route_probability_exceeds_original_route": structured_prediction_wins,
        "all_structured_permutations_predicted_route_probability_exceeds_original_route": all(structured_prediction_wins),
        "structured_permutation_predicted_route_sequence_accuracy": structured_behavior,
        "mean_structured_predicted_route_sequence_accuracy": float(np.mean(structured_behavior)),
        "collapse_original_reverse_sequence_accuracy": collapse_eval["original_reverse_sequence_accuracy"],
        "collapse_best_original_route_probability": collapse_eval["best_original_route_probability"],
        "cross_job_seed0_hash_matches_either_prior_run": final_hash in PRIOR_SEED0_FINAL_HASHES.values(),
        "portable_method_checks": {
            "baseline_behavior_prerequisite_passed": baseline_acc["sequence_accuracy"] >= 0.99,
            "identity_control_executed": True,
            "two_nontrivial_position_permutations_executed": True,
            "conjugate_route_predictions_predeclared": True,
            "position_collapse_control_executed": True,
            "attention_and_behavior_both_observed": True,
            "no_extra_seed_added": True,
        },
    }

    raw_output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    git_sha = os.environ.get("GITHUB_SHA")
    bundle = {
        "probe_id": "c1-learned-reverse-position-code-falsifier-v1",
        "instrument": "targeted-position-code-causal-routing-suite",
        "instrument_version": "mvp-1",
        "model_identity": {
            "repository": base.TRACR_REPO,
            "revision": base.TRACR_REVISION,
            "logical_id": "trained/tracr-transformer/reverse-seed0",
            "model_class": "cpu-trained-tiny-transformer",
            "final_parameter_sha256": final_hash,
        },
        "artifact_provenance": {
            "tracked": False,
            "reason": "Specimen is deterministically trained in-process from the exhaustive synthetic reverse-task universe; training code/split/seed and final parameter hash are retained.",
        },
        "access_tier": "A4",
        "evidence_level": "CAUSAL",
        "claim_tags": ["C1_CALIBRATION", "POSITION_CODE", "ATTENTION_ROUTING", "TARGETED_INTERVENTION", "FALSIFICATION"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "scope": "one seed and one learned reverse architecture; tests a specific position-code routing hypothesis rather than general transformer position mechanisms",
            "behavior": "position-table permutations perturb query/key/value/residual position information together; matching the conjugate attention route need not imply perfect conjugate output behavior",
            "hash_reproducibility": "cross-job parameter hashes are recorded descriptively; this rep does not isolate the source of prior cross-job bitwise drift",
        },
        "known_assumptions": [
            "the learned model's final attention routing is meaningfully summarized by probability and argmax alignment with the reverse route",
            "permuting only the learned absolute position table is substantially more targeted than whole-block deletion",
            "for a position-coded routing mechanism the predicted routing transformation under table permutation is conjugation P^-1 r P",
        ],
        "known_failure_modes": [
            "the model may distribute reverse computation across attention, MLP, residual, and token pathways such that attention follows the predicted conjugate route while output behavior does not",
            "position permutations can create off-training-manifold states",
            "a failed conjugate prediction would falsify this simple position-code mechanism but not all possible learned routing mechanisms",
        ],
        "cost": {
            "training_seconds": training_seconds,
            "total_script_seconds": time.perf_counter() - started,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        },
        "provenance": {
            "run_id": str(os.environ.get("GITHUB_RUN_ID", "local")),
            "code_revision": git_sha,
            "model_revision": final_hash,
            "tokenizer_revision": None,
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "numpy": np.__version__,
                "jax": jax.__version__,
                "jaxlib": importlib.metadata.version("jaxlib"),
                "dm_haiku": importlib.metadata.version("dm-haiku"),
                "tracr_source_revision": base.TRACR_REVISION,
            },
            "randomness": {"training_seed": base.SEED, "dropout": 0.0, "split": "deterministic sha256 ordering"},
            "raw_input_hash": sha256_json({
                "task": "reverse",
                "seed": base.SEED,
                "steps": base.STEPS,
                "test_x": split["test_x"].tolist(),
                "permutations": PERMUTATIONS,
                "target_route": base.TARGET_ROUTE,
            }),
            "raw_output_hash": raw_output_hash,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "final_parameter_sha256": final_hash,
        "baseline_sequence_accuracy": baseline_acc["sequence_accuracy"],
        "structured_prediction_wins": structured_prediction_wins,
        "structured_predicted_sequence_accuracy": structured_behavior,
        "collapse_reverse_sequence_accuracy": collapse_eval["original_reverse_sequence_accuracy"],
        "training_seconds": training_seconds,
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
