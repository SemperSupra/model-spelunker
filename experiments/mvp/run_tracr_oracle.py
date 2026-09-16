#!/usr/bin/env python3
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
from typing import Any, Callable

import haiku as hk
import numpy as np
from tracr.compiler import compiling
from tracr.compiler import lib
from tracr.rasp import rasp

TRACR_REPO = "google-deepmind/tracr"
TRACR_REVISION = "9ce2b8c82b6ba10e62e86cf6f390e7536d4fd2cd"
TRACR_LICENSE = "Apache-2.0"
BOS = "BOS"
PAD = "PAD"
MAX_SEQ_LEN = 5


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256_bytes(payload)


def array_hash(x: np.ndarray) -> str:
    a = np.ascontiguousarray(np.asarray(x))
    header = json.dumps({"shape": list(a.shape), "dtype": str(a.dtype)}, sort_keys=True).encode() + b"\0"
    return sha256_bytes(header + a.tobytes(order="C"))


def params_hash(params: hk.Params) -> tuple[str, int, list[dict[str, Any]]]:
    d = hk.data_structures.to_mutable_dict(params)
    h = hashlib.sha256()
    count = 0
    leaves = []
    for module in sorted(d):
        for name in sorted(d[module]):
            a = np.ascontiguousarray(np.asarray(d[module][name]))
            key = f"{module}/{name}".encode("utf-8")
            h.update(len(key).to_bytes(8, "big")); h.update(key)
            h.update(str(a.dtype).encode()); h.update(json.dumps(list(a.shape)).encode()); h.update(a.tobytes(order="C"))
            count += int(a.size)
            leaves.append({"path": f"{module}/{name}", "shape": list(a.shape), "dtype": str(a.dtype), "sha256": array_hash(a)})
    return "sha256:" + h.hexdigest(), count, leaves


def json_value(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        x = float(v)
        return int(round(x)) if abs(x - round(x)) < 1e-7 else x
    return v


def normalize_decoded(values: list[Any]) -> list[Any]:
    return [json_value(v) for v in values]


def tensor_summary(x: Any) -> dict[str, Any]:
    a = np.asarray(x)
    f = a.astype(np.float64, copy=False)
    return {
        "shape": list(a.shape),
        "dtype": str(a.dtype),
        "sha256": array_hash(a),
        "l2": float(np.linalg.norm(f)),
        "mean": float(np.mean(f)),
        "std": float(np.std(f)),
        "min": float(np.min(f)),
        "max": float(np.max(f)),
    }


def attention_summary(x: Any, num_heads: int) -> dict[str, Any]:
    a = np.asarray(x)
    out = tensor_summary(a)
    if a.ndim != 4 or a.shape[0] != 1:
        out["layout"] = "unknown"
        return out
    if a.shape[1] == num_heads:
        # [B,H,Q,K]
        logits = a[0]
        out["layout"] = "BHQK"
    elif a.shape[-1] == num_heads:
        # [B,Q,K,H] -> [H,Q,K]
        logits = np.moveaxis(a[0], -1, 0)
        out["layout"] = "BQKH"
    else:
        out["layout"] = "unknown"
        return out
    patterns = []
    for head, h in enumerate(logits):
        shifted = h - np.max(h, axis=-1, keepdims=True)
        p = np.exp(shifted)
        p /= np.sum(p, axis=-1, keepdims=True)
        entropy = -np.sum(np.where(p > 0, p * np.log(p), 0.0), axis=-1)
        patterns.append({
            "head": head,
            "argmax_key_by_query": np.argmax(h, axis=-1).astype(int).tolist(),
            "mean_attention_entropy": float(np.mean(entropy)),
            "max_probability_by_query": np.max(p, axis=-1).astype(float).tolist(),
        })
    out["heads"] = patterns
    return out


def oracle_label_indices(labels: list[str], names: list[str]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    low = [x.casefold() for x in labels]
    for name in names:
        needle = name.casefold()
        result[name] = [i for i, label in enumerate(low) if needle in label]
    return result


def subspace_energy_fraction(x: Any, indices: list[int]) -> float | None:
    if not indices:
        return None
    a = np.asarray(x, dtype=np.float64)
    total = float(np.sum(a * a))
    if total <= 1e-20:
        return 0.0
    return float(np.sum(a[..., indices] ** 2) / total)


def reverse_expected(content: list[Any]) -> list[Any]:
    return [BOS] + list(reversed(content))


def hist_expected(content: list[Any]) -> list[Any]:
    counts = {x: content.count(x) for x in set(content)}
    return [BOS] + [counts[x] for x in content]


def program_specs() -> list[dict[str, Any]]:
    return [
        {
            "id": "reverse",
            "program": lib.make_reverse(rasp.tokens),
            "vocab": {1, 2, 3},
            "oracle_names": ["tokens", "indices", "length", "opp_idx", "reverse_selector", "reverse"],
            "cases": [
                [1, 2, 3, 1],
                [3, 1, 2, 2],
                [2, 2, 1, 3],
            ],
            "expected": reverse_expected,
        },
        {
            "id": "hist",
            "program": lib.make_hist(),
            "vocab": {"a", "b", "c"},
            "oracle_names": ["tokens", "indices", "same_tok", "hist"],
            "cases": [
                ["a", "b", "a", "c"],
                ["c", "c", "b", "c"],
                ["b", "a", "b", "a"],
            ],
            "expected": hist_expected,
        },
    ]


def compile_one(spec: dict[str, Any]):
    return compiling.compile_rasp_to_model(
        spec["program"],
        vocab=spec["vocab"],
        max_seq_len=MAX_SEQ_LEN,
        causal=False,
        compiler_bos=BOS,
        compiler_pad=PAD,
    )


def run_program(spec: dict[str, Any]) -> dict[str, Any]:
    t = time.perf_counter()
    model = compile_one(spec)
    compile_seconds = time.perf_counter() - t
    repeat = compile_one(spec)
    phash, param_count, leaves = params_hash(model.params)
    repeat_hash, repeat_param_count, _ = params_hash(repeat.params)
    labels = [str(x) for x in model.residual_labels]
    label_map = oracle_label_indices(labels, spec["oracle_names"])

    config = model.model_config
    cases = []
    for index, content in enumerate(spec["cases"]):
        tokens = [BOS] + content
        out = model.apply(tokens)
        out_repeat = model.apply(tokens)
        decoded = normalize_decoded(out.decoded)
        decoded_repeat = normalize_decoded(out_repeat.decoded)
        expected = normalize_decoded(spec["expected"](content))
        residuals = [tensor_summary(x) for x in out.residuals]
        layer_outputs = [tensor_summary(x) for x in out.layer_outputs]
        attentions = [attention_summary(x, int(config.num_heads)) for x in out.attn_logits]
        named_energy = {
            name: [subspace_energy_fraction(x, indices) for x in out.residuals]
            for name, indices in label_map.items()
        }
        cases.append({
            "case_id": f"{spec['id']}-{index}",
            "input_tokens": tokens,
            "expected": expected,
            "decoded": decoded,
            "behavior_correct": decoded == expected,
            "repeat_decoded_equal": decoded_repeat == decoded,
            "transformer_output": tensor_summary(out.transformer_output),
            "input_embeddings": tensor_summary(out.input_embeddings),
            "residuals": residuals,
            "layer_outputs": layer_outputs,
            "attention_logits": attentions,
            "oracle_subspace_energy_fraction_by_residual": named_energy,
        })

    return {
        "program_id": spec["id"],
        "program_spec_hash": sha256_json({
            "id": spec["id"],
            "vocab": sorted(spec["vocab"], key=str),
            "max_seq_len": MAX_SEQ_LEN,
            "bos": BOS,
            "pad": PAD,
            "cases": spec["cases"],
        }),
        "compile_seconds": compile_seconds,
        "parameter_sha256": phash,
        "repeat_parameter_sha256": repeat_hash,
        "parameter_repeat_exact": phash == repeat_hash and param_count == repeat_param_count,
        "parameter_count": param_count,
        "parameter_leaves": leaves,
        "model_config": {
            "num_heads": int(config.num_heads),
            "num_layers": int(config.num_layers),
            "key_size": int(config.key_size),
            "mlp_hidden_size": int(config.mlp_hidden_size),
            "layer_norm": bool(config.layer_norm),
            "causal": bool(config.causal),
        },
        "residual_labels": labels,
        "oracle_label_indices": label_map,
        "oracle_label_coverage": {name: len(indices) for name, indices in label_map.items()},
        "cases": cases,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/tracr-oracle.json"))
    args = ap.parse_args()
    started = time.perf_counter()

    programs = [run_program(spec) for spec in program_specs()]
    all_behavior_correct = all(c["behavior_correct"] for p in programs for c in p["cases"])
    all_apply_repeats = all(c["repeat_decoded_equal"] for p in programs for c in p["cases"])
    all_parameter_repeats = all(p["parameter_repeat_exact"] for p in programs)
    oracle_surfaces_present = all(
        p["residual_labels"]
        and all(len(c["residuals"]) == 2 * p["model_config"]["num_layers"] for c in p["cases"])
        and all(len(c["layer_outputs"]) == 2 * p["model_config"]["num_layers"] for c in p["cases"])
        and all(len(c["attention_logits"]) == p["model_config"]["num_layers"] for c in p["cases"])
        for p in programs
    )
    ground_truth_labels_found = all(
        len(p["oracle_label_indices"].get(p["program_id"], [])) > 0 for p in programs
    )

    observations = {
        "source": {
            "repository": TRACR_REPO,
            "exact_revision": TRACR_REVISION,
            "license": TRACR_LICENSE,
            "archived_read_only_specimen": True,
        },
        "protocol": {
            "compiler": "tracr.compiler.compiling.compile_rasp_to_model",
            "programs": ["reverse", "hist"],
            "max_seq_len": MAX_SEQ_LEN,
            "bos": BOS,
            "pad": PAD,
            "causal": False,
            "raw_tensor_persistence": False,
            "oracle_basis": "Tracr residual_labels emitted by the compiler",
        },
        "programs": programs,
    }
    derived = {
        "all_behavior_correct": all_behavior_correct,
        "all_apply_repeats_exact": all_apply_repeats,
        "all_parameter_repeats_exact": all_parameter_repeats,
        "oracle_surfaces_present": oracle_surfaces_present,
        "ground_truth_output_labels_found": ground_truth_labels_found,
        "program_count": len(programs),
        "case_count": sum(len(p["cases"]) for p in programs),
        "portable_method_checks": {
            "compiled_oracle_behavior_checked": all_behavior_correct,
            "compiled_parameter_identity_repeated": all_parameter_repeats,
            "residual_basis_ground_truth_retained": ground_truth_labels_found,
            "residual_observation_available": oracle_surfaces_present,
            "layer_output_observation_available": oracle_surfaces_present,
            "attention_logit_observation_available": oracle_surfaces_present,
            "raw_tensors_reduced_before_artifact": True,
        },
    }
    raw_output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    git_sha = os.environ.get("GITHUB_SHA")
    bundle = {
        "probe_id": "c1-tracr-oracle-calibration-v1",
        "instrument": "compiled-transformer-ground-truth-oracle-suite",
        "instrument_version": "mvp-1",
        "model_identity": {
            "repository": TRACR_REPO,
            "revision": TRACR_REVISION,
            "logical_id": "compiled/tracr/reverse+hist",
            "model_class": "compiled-routine-transformers",
            "parameter_digests": {p["program_id"]: p["parameter_sha256"] for p in programs},
        },
        "artifact_provenance": {
            "tracked": False,
            "reason": "No external large model artifact exists: both tiny transformer parameter sets are compiled in-process from the exact pinned Tracr source revision and fully identified by retained program specs plus parameter SHA-256 digests."
        },
        "access_tier": "A2",
        "evidence_level": "REPRODUCED",
        "claim_tags": ["C1_CALIBRATION", "TRACR", "COMPILED_ORACLE", "GROUND_TRUTH_SUBSPACES", "ATTENTION_ORACLE"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "scope": "qualification of the oracle substrate on two small compiled RASP programs; no claim yet that Model Spelunker discovery methods recover the known mechanism",
            "ground_truth": "residual labels/subspaces are compiler-provided oracle structure, not inferred labels",
        },
        "known_assumptions": [
            "Tracr's compiler-provided residual basis is suitable ground truth for later interpretability-method calibration",
            "reverse and hist are sufficient to qualify the initial compiler/instrument compatibility path",
        ],
        "known_failure_modes": [
            "compiled transformers are deliberately clean and may not represent superposed mechanisms in trained models",
            "two programs do not span the RASP/Tracr mechanism space",
            "generic summaries can be valid observations without being sufficient for mechanism recovery",
        ],
        "cost": {
            "experiment_seconds": time.perf_counter() - started,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        },
        "provenance": {
            "run_id": str(os.environ.get("GITHUB_RUN_ID", "local")),
            "code_revision": git_sha,
            "model_revision": TRACR_REVISION,
            "tokenizer_revision": None,
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "numpy": np.__version__,
                "jax": importlib.metadata.version("jax"),
                "jaxlib": importlib.metadata.version("jaxlib"),
                "dm_haiku": importlib.metadata.version("dm-haiku"),
                "chex": importlib.metadata.version("chex"),
                "tracr_source_revision": TRACR_REVISION,
            },
            "randomness": {"compiler": "direct construction; no gradient training", "dropout": 0.0},
            "raw_input_hash": sha256_json({"tracr_revision": TRACR_REVISION, "program_specs": [p["program_spec_hash"] for p in programs]}),
            "raw_output_hash": raw_output_hash,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "all_behavior_correct": all_behavior_correct,
        "all_parameter_repeats_exact": all_parameter_repeats,
        "ground_truth_output_labels_found": ground_truth_labels_found,
        "programs": {p["program_id"]: {"params": p["parameter_count"], "layers": p["model_config"]["num_layers"], "heads": p["model_config"]["num_heads"], "residual_dims": len(p["residual_labels"])} for p in programs},
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
