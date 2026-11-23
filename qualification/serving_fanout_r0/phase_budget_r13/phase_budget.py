#!/usr/bin/env python3
"""R13 independent phase/resource reducer for existing #316 Ollama receipts.

No inference, routing, task validation or authority changes. Python stdlib only.
Unknown measurement is never converted to zero or a qualified-route claim.
"""
import argparse
import hashlib
import json
import math
import pathlib
import re
import statistics

EVIDENCE = "REAL_PUBLIC_CPU_STREAMING_DIRECT_INFERENCE_EXPLORATORY"
FIELDS = ("cpu", "memory", "gpu", "vram")
SOURCES = {
    "cpu": ("cgroup-v2-quota", "visible-cpu-proxy"),
    "memory": ("cgroup-v2-limit", "host-meminfo-proxy"),
    "gpu": ("verified-device-counter",),
    "vram": ("verified-device-counter",),
}

class InvalidReceipt(ValueError):
    pass

def number(v, name, *, positive=False, integral=False):
    if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v):
        raise InvalidReceipt(name + ": expected finite number (not bool)")
    if (positive and v <= 0) or (not positive and v < 0):
        raise InvalidReceipt(name + ": negative or zero")
    if integral and (not isinstance(v, int) or isinstance(v, bool)):
        raise InvalidReceipt(name + ": expected integer")
    return v

def percentile(data, pct):
    if not data:
        return None
    values = sorted(data)
    return values[math.ceil(pct * len(values)) - 1]

def load_json(path):
    b = pathlib.Path(path).read_bytes()
    if len(b) > 4 * 1024 * 1024:
        raise InvalidReceipt("input exceeds 4MiB")
    try:
        return json.loads(b, parse_constant=lambda _: (_ for _ in ()).throw(InvalidReceipt("nonfinite JSON")))
    except (ValueError, TypeError) as exc:
        raise InvalidReceipt("invalid JSON: " + str(exc)) from exc

def condition_id(c):
    n = number(c.get("client_concurrency"), "concurrency", positive=True, integral=True)
    rep = number(c.get("replicate"), "replicate", positive=True, integral=True)
    kind = c.get("prefix_kind")
    if n not in (1, 2, 4, 8) or kind not in ("shared", "distinct"):
        raise InvalidReceipt("unsupported concurrency/prefix")
    return "r%d-c%d-%s" % (rep, n, kind)

def reduce_phase(report):
    if not isinstance(report, dict) or report.get("evidence_class") != EVIDENCE:
        raise InvalidReceipt("wrong direct-inference evidence class")
    digest = report.get("runtime_model_digest")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise InvalidReceipt("missing exact runtime-model digest")
    if report.get("agent_task_validity") != "NOT_TESTED":
        raise InvalidReceipt("external task validation cannot be inferred from direct inference")
    conditions = report.get("conditions")
    if not isinstance(conditions, list) or not conditions or len(conditions) > 64:
        raise InvalidReceipt("invalid condition count")
    cells = []
    seen = set()
    for c in conditions:
        if not isinstance(c, dict):
            raise InvalidReceipt("invalid condition shape")
        key = condition_id(c)
        if key in seen:
            raise InvalidReceipt("duplicate condition identity")
        seen.add(key)
        wall = number(c.get("wall_ms"), key + ".wall_ms", positive=True)
        samples = c.get("samples")
        if not isinstance(samples, list) or not 1 <= len(samples) <= 32:
            raise InvalidReceipt("invalid sample cardinality")
        ttfts, latencies = [], []
        prompt_toks = output_toks = prefill_ms = decode_ms = load_ms = 0
        for sample in samples:
            if not isinstance(sample, dict):
                raise InvalidReceipt("malformed sample")
            ttft = number(sample.get("ttft_ms"), "ttft", positive=True)
            elapsed = number(sample.get("elapsed_ms"), "elapsed", positive=True)
            if ttft > elapsed or elapsed > wall * 1.05 + 10:
                raise InvalidReceipt("impossible client chronology")
            ttfts.append(ttft)
            latencies.append(elapsed)
            prompt_toks += number(sample.get("prompt_tokens"), "prompt_tokens", positive=True, integral=True)
            output_toks += number(sample.get("output_tokens"), "output_tokens", positive=True, integral=True)
            prefill_ms += number(sample.get("prefill_ms"), "prefill_ms")
            decode_ms += number(sample.get("decode_ms"), "decode_ms")
            load_ms += number(sample.get("load_ms"), "load_ms")
        cells.append({
            "cell_id": key, "replicate": c["replicate"],
            "client_concurrency": c["client_concurrency"], "prefix_kind": c["prefix_kind"],
            "requests": len(samples), "wall_ms": wall,
            "ttft_p50_ms": percentile(ttfts, .5), "ttft_p95_ms": percentile(ttfts, .95),
            "e2e_p95_ms": percentile(latencies, .95),
            "prompt_tokens": prompt_toks, "output_tokens": output_toks,
            "prefill_ms_sum": prefill_ms, "decode_ms_sum": decode_ms,
            "load_ms_sum": load_ms,
            "prefill_tps_engine_sum_ratio": round(1000 * prompt_toks / prefill_ms, 3) if prefill_ms else None,
            "decode_tps_engine_sum_ratio": round(1000 * output_toks / decode_ms, 3) if decode_ms else None,
            "aggregate_output_tps_wall": round(1000 * output_toks / wall, 3),
            "goodput_verified_tasks_per_hour": None,
            "goodput_reason": "NO_INDEPENDENT_TASK_VALIDATION",
            "phase_accounting": "ENGINE_REPORTED_DURATION_NOT_ADDITIVE_TO_WALL_UNDER_CONCURRENCY",
        })
    return cells, digest

def resource_projection(resource, keys, required, reserve_fraction):
    if resource is None:
        return {k: {"status": "UNKNOWN_NO_HOST_OBSERVATIONS"} for k in keys}
    if not isinstance(resource, dict) or resource.get("schema") != "serving-phase-resource-r13/v1":
        raise InvalidReceipt("unknown resource-source schema")
    samples = resource.get("cells")
    if not isinstance(samples, list) or len(samples) > 64:
        raise InvalidReceipt("invalid resource cells")
    by_id = {}
    for cell in samples:
        if not isinstance(cell, dict) or not isinstance(cell.get("cell_id"), str):
            raise InvalidReceipt("invalid resource cell identity")
        key = cell["cell_id"]
        if key in by_id or key not in keys:
            raise InvalidReceipt("duplicate or unreferenced resource cell")
        by_id[key] = cell
    results = {}
    for key in keys:
        cell = by_id.get(key)
        if cell is None:
            results[key] = {"status": "UNKNOWN_NO_MATCHED_RESOURCE_CELL"}
            continue
        readings = cell.get("readings")
        if not isinstance(readings, list) or len(readings) > 10000:
            raise InvalidReceipt("invalid resource readings")
        peak = {}
        missing = []
        weak = []
        for name in required:
            seen = []
            for r in readings:
                if not isinstance(r, dict):
                    raise InvalidReceipt("malformed resource reading")
                v = r.get(name)
                if v is not None:
                    seen.append(number(v, name))
            if len(seen) < 2:
                missing.append(name)
                continue
            peak[name] = round(max(seen), 6)
            basis = cell.get("sources", {}).get(name)
            if basis not in SOURCES[name]:
                raise InvalidReceipt("unapproved resource measurement source")
            if "proxy" in basis:
                weak.append(name)
        if missing:
            results[key] = {"status": "UNKNOWN_INCOMPLETE_RESOURCE_COVERAGE",
                            "missing": missing, "peak_observed": peak}
            continue
        max_fraction = max(peak.values())
        observed_margin = 1.0 - max_fraction
        status = "OBSERVED_PROXY_ONLY" if weak else "OBSERVED_BOUNDED_NOT_SURGE_GUARANTEED"
        results[key] = {"status": status, "peak_fraction": peak,
                        "observed_free_fraction_lower_bound": round(observed_margin, 6),
                        "min_reserve_target": reserve_fraction,
                        "resource_threshold_met": observed_margin >= reserve_fraction,
                        "weak_capacity_sources": weak,
                        "warning": "Snapshot headroom cannot establish reservable surge capacity, fairness or future hardware availability"}
    return results

def reduce(report, resources=None, *, required=("cpu", "memory"), reserve=.25, ttft_slo_ms=3000):
    if not 0 < reserve < 1 or not ttft_slo_ms > 0 or any(r not in FIELDS for r in required) or not required:
        raise InvalidReceipt("invalid reservation/SLO dimensions")
    cells, digest = reduce_phase(report)
    res = resource_projection(resources, {c["cell_id"] for c in cells}, required, reserve)
    for cell in cells:
        cell["resource_headroom"] = res[cell["cell_id"]]
        cell["interactive_ttft_slo_met"] = cell["ttft_p95_ms"] <= ttft_slo_ms
        cell["route_qualified"] = False
        cell["promotion"] = "HOLD_NO_VALIDATED_TASK_GOODPUT_OR_COMPLETE_SURGE_EVIDENCE"
    return {
        "schema": "serving-phase-budget-r13/v1",
        "evidence_class": "DERIVED_DIRECT_INFERENCE_EXPLORATORY_NOT_ACTOR_QUALIFICATION",
        "runtime_model_digest": digest,
        "input_receipt_sha256": hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "required_resource_dimensions": list(required),
        "minimum_observed_free_fraction_target": reserve,
        "interactive_ttft_slo_ms": ttft_slo_ms,
        "source_scope": "PUBLIC_RUNNER_INFERENCE_ONLY",
        "goodput_verified_tasks_per_hour": None,
        "goodput_verification": "NOT_MEASURED_REQUIRES_EXISTING_139_INDEPENDENT_VALIDATOR",
        "gpu_and_kv_metrics": "UNKNOWN_UNLESS_EXPLICITLY_OBSERVED_BY_VALIDATED_SENSOR",
        "cells": cells,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--resources")
    ap.add_argument("--out", required=True)
    ap.add_argument("--required", default="cpu,memory")
    ap.add_argument("--reserve", type=float, default=.25)
    ap.add_argument("--ttft-slo-ms", type=float, default=3000)
    args = ap.parse_args()
    try:
        required = tuple(args.required.split(","))
        if len(set(required)) != len(required):
            raise InvalidReceipt("repeated required resource")
        result = reduce(load_json(args.input), load_json(args.resources) if args.resources else None,
                        required=required, reserve=args.reserve, ttft_slo_ms=args.ttft_slo_ms)
        pathlib.Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print("R13_PHASE_CELLS=%d GOODPUT=UNKNOWN PROMOTION=HOLD" % len(result["cells"]))
    except (InvalidReceipt, OSError) as exc:
        ap.exit(2, "R13_REJECTED: %s\n" % exc)

if __name__ == "__main__":
    main()
