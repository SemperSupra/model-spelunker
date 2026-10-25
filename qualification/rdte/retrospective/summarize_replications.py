#!/usr/bin/env python3
"""Summarize repeated prospective telemetry reps within each harness family.

RDT&E only: model-spelunker#114 / agent-dispatch-private#314.

This reducer compares repeated runs of the *same configured treatment*. It does
not score or rank harnesses against each other. Native process variants are
preserved per family; coarse anchors are reported only as descriptive evidence.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from qualification.rdte.retrospective.analyze_process_variants import (
    summarize_goose_trace,
    summarize_openworker_trace,
)


def _find(root: Path, name: str) -> Path:
    if root.is_file() and root.name == name:
        return root
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {name} under {root}, found {len(matches)}"
        )
    return matches[0]


def _numeric_stats(values: list[int | float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    xs = [float(value) for value in values]
    out: dict[str, Any] = {
        "count": len(xs),
        "min": min(xs),
        "max": max(xs),
        "mean": statistics.fmean(xs),
    }
    if len(xs) >= 2:
        out["pstdev"] = statistics.pstdev(xs)
    else:
        out["pstdev"] = 0.0
    return out


def _variant_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load_rep(root: Path, family: str) -> dict[str, Any]:
    trace_path = _find(root, "trace.json")
    run_path = _find(root, "run-summary.json")
    run = json.loads(run_path.read_text(encoding="utf-8"))

    if family == "goose":
        process = summarize_goose_trace(trace_path)
    elif family == "openworker":
        process = summarize_openworker_trace(trace_path)
    else:
        raise ValueError(f"unsupported family: {family}")

    execution = run.get("execution")
    execution = execution if isinstance(execution, dict) else {}
    resources = run.get("resources")
    resources = resources if isinstance(resources, dict) else {}
    trace_summary = run.get("trace_summary")
    trace_summary = trace_summary if isinstance(trace_summary, dict) else {}

    return {
        "family": family,
        "artifact_root": str(root),
        "candidate_exit_code": execution.get("candidate_exit_code"),
        "state_changed": execution.get("state_changed"),
        "verifier_pass": execution.get("verifier_pass"),
        "wall_seconds": resources.get("wall_seconds"),
        "max_rss_kbytes": resources.get("max_rss_kbytes"),
        "source_event_count": process.get("source_event_count"),
        "process_native_token_count": process.get("native_token_count"),
        "message_group_count": process.get("message_group_count"),
        "anchor_variant": process.get("anchor_variant", []),
        "native_variant_rle": process.get("native_variant_rle", []),
        "tool_names": process.get("tool_names", []),
        "trace_event_count": trace_summary.get("event_count"),
        "model_call_started_count": trace_summary.get("model_call_started_count"),
        "provider_observation_count": trace_summary.get("provider_observation_count"),
        "assistant_message_groups": trace_summary.get("assistant_message_groups"),
        "tool_request_count": trace_summary.get("tool_request_count"),
        "tool_response_count": trace_summary.get("tool_response_count"),
        "tool_error_count": trace_summary.get("tool_error_count"),
    }


def _cohort(family: str, reps: list[dict[str, Any]]) -> dict[str, Any]:
    if not reps:
        raise ValueError(f"{family} cohort is empty")

    native_variants = Counter(_variant_key(rep["native_variant_rle"]) for rep in reps)
    anchor_variants = Counter(_variant_key(rep["anchor_variant"]) for rep in reps)
    outcomes = Counter(
        _variant_key({
            "candidate_exit_code": rep["candidate_exit_code"],
            "state_changed": rep["state_changed"],
            "verifier_pass": rep["verifier_pass"],
        })
        for rep in reps
    )

    numeric_fields = (
        "wall_seconds",
        "max_rss_kbytes",
        "trace_event_count",
        "process_native_token_count",
        "model_call_started_count",
        "provider_observation_count",
        "assistant_message_groups",
        "tool_request_count",
        "tool_response_count",
        "tool_error_count",
    )
    metrics = {}
    for field in numeric_fields:
        values = [
            rep[field]
            for rep in reps
            if isinstance(rep.get(field), (int, float))
            and not isinstance(rep.get(field), bool)
        ]
        if values:
            metrics[field] = _numeric_stats(values)

    return {
        "family": family,
        "rep_count": len(reps),
        "outcome_variant_count": len(outcomes),
        "native_process_variant_count": len(native_variants),
        "coarse_anchor_variant_count": len(anchor_variants),
        "native_process_variants": [
            {"variant": json.loads(key), "count": count}
            for key, count in native_variants.most_common()
        ],
        "coarse_anchor_variants": [
            {"variant": json.loads(key), "count": count}
            for key, count in anchor_variants.most_common()
        ],
        "outcome_variants": [
            {"outcome": json.loads(key), "count": count}
            for key, count in outcomes.most_common()
        ],
        "metrics": metrics,
        "reps": reps,
    }


def summarize(
    *,
    goose_roots: list[Path],
    openworker_roots: list[Path],
) -> dict[str, Any]:
    cohorts = []
    if goose_roots:
        cohorts.append(
            _cohort("goose", [_load_rep(root, "goose") for root in goose_roots])
        )
    if openworker_roots:
        cohorts.append(
            _cohort(
                "openworker",
                [_load_rep(root, "openworker") for root in openworker_roots],
            )
        )

    return {
        "record_type": "prospective-telemetry-replication-summary",
        "schema_version": 1,
        "cohorts": cohorts,
        "interpretation": {
            "within_treatment_replication_only": True,
            "cross_harness_ranking_performed": False,
            "conformance_model_built": False,
            "hidden_reasoning_inferred": False,
            "qualification_state_changed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goose-artifact", type=Path, action="append", default=[])
    parser.add_argument(
        "--openworker-artifact", type=Path, action="append", default=[]
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = summarize(
        goose_roots=args.goose_artifact,
        openworker_roots=args.openworker_artifact,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    compact = {
        "cohorts": [
            {
                "family": cohort["family"],
                "rep_count": cohort["rep_count"],
                "outcome_variant_count": cohort["outcome_variant_count"],
                "native_process_variant_count": cohort["native_process_variant_count"],
                "coarse_anchor_variant_count": cohort["coarse_anchor_variant_count"],
                "metrics": cohort["metrics"],
            }
            for cohort in result["cohorts"]
        ],
        "interpretation": result["interpretation"],
    }
    print(json.dumps(compact, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
