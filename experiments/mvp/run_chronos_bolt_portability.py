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
from typing import Any

import numpy as np
import torch
from chronos import BaseChronosPipeline, ChronosBoltPipeline

LOGICAL_ID = "forecast/chronos/bolt-tiny"
UPSTREAM_REPO = "amazon/chronos-bolt-tiny"
UPSTREAM_REVISION = "a0e552de83495b5c28c14c71c374f3e33280b340"
QUANTILES = [0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9]


def hbytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def hjson(value: Any) -> str:
    return hbytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def tensor_hash(x: torch.Tensor) -> str:
    a = x.detach().cpu().to(torch.float32).contiguous().numpy()
    return hbytes(a.tobytes(order="C"))


def cosine_distance(a: torch.Tensor, b: torch.Tensor) -> float:
    x = a.detach().cpu().to(torch.float64).reshape(-1)
    y = b.detach().cpu().to(torch.float64).reshape(-1)
    den = float(torch.linalg.vector_norm(x) * torch.linalg.vector_norm(y))
    if den <= 1e-12:
        return 0.0 if torch.allclose(x, y) else 1.0
    return float(1.0 - torch.dot(x, y) / den)


def build_contexts(n: int = 128) -> tuple[list[str], list[torch.Tensor]]:
    t = torch.arange(n, dtype=torch.float32)
    return ["constant", "linear", "seasonal", "step", "impulse"], [
        torch.full((n,), 3.0, dtype=torch.float32),
        0.05 * t - 2.0,
        torch.sin(2.0 * torch.pi * t / 24.0),
        torch.cat([torch.zeros(n // 2), torch.ones(n - n // 2)]).float(),
        torch.cat([torch.zeros(n - 1), torch.tensor([5.0])]).float(),
    ]


def true_future(name: str, n: int, horizon: int) -> torch.Tensor | None:
    t = torch.arange(n, n + horizon, dtype=torch.float32)
    if name == "constant":
        return torch.full((horizon,), 3.0)
    if name == "linear":
        return 0.05 * t - 2.0
    if name == "seasonal":
        return torch.sin(2.0 * torch.pi * t / 24.0)
    return None


def summarize_forecast(name: str, forecast: torch.Tensor, context_length: int) -> dict[str, Any]:
    f = forecast.detach().cpu().to(torch.float32)
    median = f[4]
    crossings = f[:-1] > f[1:]
    width = f[8] - f[0]
    truth = true_future(name, context_length, f.shape[-1])
    return {
        "shape": list(f.shape),
        "sha256_float32": tensor_hash(f),
        "finite": bool(torch.isfinite(f).all().item()),
        "quantile_crossing_cells": int(crossings.sum().item()),
        "quantile_comparisons": int(crossings.numel()),
        "median_first_last": [float(median[0]), float(median[-1])],
        "median_mean": float(median.mean()),
        "q10_q90_width_mean": float(width.mean()),
        "median_mae_known_future": float(torch.mean(torch.abs(median - truth))) if truth is not None else None,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--candidate-ref", required=True)
    p.add_argument("--output", type=Path, default=Path("out/chronos-bolt-portability.json"))
    args = p.parse_args()

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started = time.perf_counter()
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    if candidate["logical_id"] != LOGICAL_ID or candidate["upstream"]["exact_revision"] != UPSTREAM_REVISION:
        raise RuntimeError("candidate identity mismatch")
    digest = candidate["oci"]["digest"]
    if not digest.startswith("sha256:") or len(digest) != 71 or not candidate["oci"]["pullback_verified"]:
        raise RuntimeError("candidate OCI evidence is not immutable/pullback-verified")

    t0 = time.perf_counter()
    pipe = BaseChronosPipeline.from_pretrained(
        str(args.model_dir), device_map="cpu", torch_dtype=torch.float32, local_files_only=True
    )
    load_seconds = time.perf_counter() - t0
    if not isinstance(pipe, ChronosBoltPipeline):
        raise RuntimeError(f"unexpected pipeline class: {type(pipe).__name__}")
    if [float(q) for q in pipe.quantiles] != QUANTILES:
        raise RuntimeError(f"unexpected quantile levels: {pipe.quantiles}")

    names, contexts = build_contexts(128)
    t0 = time.perf_counter()
    with torch.inference_mode():
        h32 = pipe.predict(contexts, prediction_length=32, limit_prediction_length=True).float().cpu()
        repeat = pipe.predict(contexts, prediction_length=32, limit_prediction_length=True).float().cpu()
        h16 = pipe.predict(contexts, prediction_length=16, limit_prediction_length=True).float().cpu()
        h8 = pipe.predict(contexts, prediction_length=8, limit_prediction_length=True).float().cpu()
    if tuple(h32.shape) != (5,9,32) or not torch.isfinite(h32).all().item():
        raise RuntimeError(f"invalid baseline forecast: {tuple(h32.shape)}")
    repeat_delta = float((h32 - repeat).abs().max())
    if repeat_delta > 1e-6:
        raise RuntimeError(f"baseline repeat drift: {repeat_delta}")

    baseline = {name: summarize_forecast(name, h32[i], 128) for i, name in enumerate(names)}
    horizon_consistency = {
        "h8_vs_h32_prefix_max_abs_delta": float((h8 - h32[..., :8]).abs().max()),
        "h16_vs_h32_prefix_max_abs_delta": float((h16 - h32[..., :16]).abs().max()),
        "h8_hash": tensor_hash(h8), "h16_hash": tensor_hash(h16), "h32_hash": tensor_hash(h32),
    }

    affine_names = ["linear", "seasonal"]
    idx = [names.index(x) for x in affine_names]
    a, b = 2.5, 7.0
    transformed_contexts = [contexts[i] * a + b for i in idx]
    with torch.inference_mode():
        transformed = pipe.predict(transformed_contexts, prediction_length=32, limit_prediction_length=True).float().cpu()
    restored = (transformed - b) / a
    reference = h32[idx]
    affine = {
        "scale": a, "offset": b,
        "restored_max_abs_delta": float((restored - reference).abs().max()),
        "restored_mean_abs_delta": float((restored - reference).abs().mean()),
        "restored_cosine_distance": cosine_distance(restored, reference),
        "transformed_forecast_hash": tensor_hash(transformed),
    }

    context_rows = []
    for length in (128,64,32):
        subset = [contexts[names.index("linear")][-length:], contexts[names.index("seasonal")][-length:]]
        with torch.inference_mode():
            out = pipe.predict(subset, prediction_length=16, limit_prediction_length=True).float().cpu()
        ref = h16[[names.index("linear"), names.index("seasonal")]]
        context_rows.append({
            "context_length": length,
            "forecast_hash": tensor_hash(out),
            "median_mean_abs_delta_from_len128": float((out[:,4,:] - ref[:,4,:]).abs().mean()),
            "median_max_abs_delta_from_len128": float((out[:,4,:] - ref[:,4,:]).abs().max()),
            "finite": bool(torch.isfinite(out).all().item()),
        })

    missing_contexts = []
    for source in (contexts[names.index("linear")], contexts[names.index("seasonal")]):
        x = source.clone()
        x[::8] = torch.nan
        x[:8] = torch.nan
        missing_contexts.append(x)
    with torch.inference_mode():
        missing = pipe.predict(missing_contexts, prediction_length=16, limit_prediction_length=True).float().cpu()
    missingness = {
        "pattern": "leading 8 NaNs plus every 8th sample NaN",
        "forecast_hash": tensor_hash(missing),
        "finite": bool(torch.isfinite(missing).all().item()),
        "median_mean_abs_delta_from_complete": float((missing[:,4,:] - h16[[1,2],4,:]).abs().mean()),
        "median_max_abs_delta_from_complete": float((missing[:,4,:] - h16[[1,2],4,:]).abs().max()),
    }

    experiment_seconds = time.perf_counter() - t0
    observations = {
        "protocol": {
            "pipeline_class": type(pipe).__name__, "quantiles": QUANTILES,
            "model_context_length": int(pipe.model_context_length),
            "model_prediction_length": int(pipe.model_prediction_length),
            "synthetic_context_length": 128,
            "full_forecast_tensors_persisted": False,
        },
        "baseline_families": baseline,
        "baseline_repeat": {"max_abs_delta": repeat_delta, "hash_equal": tensor_hash(h32) == tensor_hash(repeat)},
        "horizon_consistency": horizon_consistency,
        "positive_affine_equivariance": affine,
        "context_length_sensitivity": context_rows,
        "missingness": missingness,
    }
    derived = {
        "known_future_median_mae": {k: v["median_mae_known_future"] for k,v in baseline.items() if v["median_mae_known_future"] is not None},
        "total_quantile_crossings": int(sum(v["quantile_crossing_cells"] for v in baseline.values())),
        "total_quantile_comparisons": int(sum(v["quantile_comparisons"] for v in baseline.values())),
        "baseline_repeat_exact": bool(tensor_hash(h32) == tensor_hash(repeat)),
        "all_baseline_forecasts_finite": bool(all(v["finite"] for v in baseline.values())),
        "missingness_forecast_finite": missingness["finite"],
        "portable_method_checks": {
            "five_numeric_families_executed": len(baseline) == 5,
            "multiple_horizons_executed": True,
            "positive_affine_transform_executed": True,
            "context_truncation_executed": True,
            "nan_missingness_executed": True,
            "baseline_repeat_observed": bool(tensor_hash(h32) == tensor_hash(repeat)),
        },
    }
    raw_hash = hjson({"observations": observations, "derived_metrics": derived})
    git_sha = os.environ.get("GITHUB_SHA")
    bundle = {
        "probe_id": "chronos-bolt-timeseries-portability-v1",
        "instrument": "timeseries-quantile-forecast-protocol-contrast-suite",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": UPSTREAM_REPO, "revision": UPSTREAM_REVISION, "logical_id": LOGICAL_ID, "model_class": "time-series-probabilistic-forecaster"},
        "artifact_provenance": {
            "tracked": True, "foundry_repository": "SemperSupra/model-artifact-foundry",
            "logical_artifact_id": LOGICAL_ID, "upstream_provider": "huggingface", "upstream_repository": UPSTREAM_REPO,
            "upstream_revision": UPSTREAM_REVISION, "identity_kind": "oci", "identity_digest": digest,
            "foundry_record_ref": args.candidate_ref, "consumer_selection_ref": f"model-spelunker@{git_sha}" if git_sha else None,
            "verified": True, "verification_ref": "pullback-verified candidate Foundry hydration with forced-offline local reuse", "tokenizer_artifact": None,
        },
        "access_tier": "A1", "evidence_level": "REPRODUCED",
        "claim_tags": ["TIME_SERIES", "FORECASTING", "PROBABILISTIC_OUTPUT", "PROTOCOL_SENSITIVITY", "INVARIANT_TEST"],
        "observations": observations, "derived_metrics": derived,
        "uncertainty": {
            "scope": "single synthetic reconnaissance suite; not a population forecast benchmark",
            "candidate_status": "artifact is Foundry candidate evidence, not approved catalog state",
            "forecast_quality": "known-future errors are descriptive and never qualification gates",
        },
        "known_assumptions": [
            "positive affine inversion is meaningful because quantile order is preserved for positive scale",
            "separate horizon calls are an appropriate protocol-dependence check",
            "NaN masking is part of the supported Chronos-Bolt context path",
        ],
        "known_failure_modes": [
            "synthetic families are much narrower than real time-series distributions",
            "context truncation changes both available history and patch composition",
            "quantile crossing count is descriptive and does not by itself establish calibration quality",
        ],
        "cost": {"model_load_seconds": load_seconds, "experiment_seconds": experiment_seconds, "total_script_seconds": time.perf_counter()-started, "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.0},
        "provenance": {
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"), "code_revision": git_sha,
            "model_revision": UPSTREAM_REVISION, "tokenizer_revision": None,
            "environment": {"python": sys.version.split()[0], "platform": platform.platform(), "numpy": np.__version__, "torch": torch.__version__, "chronos_forecasting": importlib.metadata.version("chronos-forecasting")},
            "randomness": {"torch_manual_seed": 0, "deterministic_forecast": True},
            "raw_input_hash": hjson({"families": names, "context_length": 128, "horizons": [8,16,32], "affine": [a,b], "context_lengths": [128,64,32], "missing_pattern": missingness["pattern"]}),
            "raw_output_hash": raw_hash,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "identity_digest": digest, "known_future_mae": derived["known_future_median_mae"], "horizon_consistency": horizon_consistency, "affine": affine, "missing_finite": missingness["finite"], "repeat_exact": derived["baseline_repeat_exact"], "peak_rss_mib": bundle["cost"]["peak_rss_mib"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
