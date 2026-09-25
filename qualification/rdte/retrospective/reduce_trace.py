#!/usr/bin/env python3
"""Deterministic reducer for public-safe retrospective trajectory manifests.

RDT&E only: model-spelunker#114 / agent-dispatch-private#314.

The reducer never fetches remote data, never reads hidden reasoning, and never
updates actor qualification state. It derives a small set of mechanically
checkable process signals from source-bound observable events.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

ALLOWED_TRACE_QUALITY = {"complete", "partial", "censored", "unknown"}
ALLOWED_TYPES = {
    "DISPATCH",
    "PROVIDER_ADMIT",
    "PROVIDER_REJECT",
    "OBSERVE",
    "PLAN",
    "MODEL_CALL",
    "TOOL_CALL",
    "TOOL_RESULT",
    "MUTATE",
    "VALIDATE",
    "FEEDBACK",
    "REPAIR",
    "REPLAN",
    "ESCALATE",
    "HANDOFF",
    "COMPLETE",
    "FAIL",
    "UNKNOWN_GAP",
}
ALLOWED_STATUS = {"success", "error", "pass", "fail", "timeout", "unknown", None}


class TraceError(ValueError):
    pass


def _time(value: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise TraceError("event.at must be a non-empty ISO-8601 string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TraceError(f"invalid event time: {value!r}") from exc
    if parsed.tzinfo is None:
        raise TraceError("event.at must include timezone")
    return parsed.astimezone(dt.timezone.utc)


def _seconds(a: dt.datetime, b: dt.datetime) -> float:
    return max(0.0, (b - a).total_seconds())


def _load(manifest: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(manifest, dict):
        raise TraceError("manifest root must be an object")
    if manifest.get("schema_version") != 1:
        raise TraceError("schema_version must be 1")
    rep_id = manifest.get("rep_id")
    actor_family = manifest.get("actor_family")
    trace_quality = manifest.get("trace_quality")
    if not isinstance(rep_id, str) or not rep_id:
        raise TraceError("rep_id is required")
    if not isinstance(actor_family, str) or not actor_family:
        raise TraceError("actor_family is required")
    if trace_quality not in ALLOWED_TRACE_QUALITY:
        raise TraceError("unsupported trace_quality")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise TraceError("at least one source is required")
    source_refs = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise TraceError(f"sources[{index}] must be an object")
        ref = source.get("ref")
        if not isinstance(ref, str) or not ref:
            raise TraceError(f"sources[{index}].ref is required")
        source_refs.add(ref)

    events = manifest.get("events")
    if not isinstance(events, list) or not events:
        raise TraceError("events must be a non-empty array")

    normalized: list[dict[str, Any]] = []
    previous: dt.datetime | None = None
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise TraceError(f"events[{index}] must be an object")
        kind = event.get("type")
        if kind not in ALLOWED_TYPES:
            raise TraceError(f"unsupported event type: {kind!r}")
        at = _time(event.get("at"))
        if previous is not None and at < previous:
            raise TraceError("events must be chronological")
        previous = at
        source_ref = event.get("source_ref")
        if source_ref not in source_refs:
            raise TraceError(f"event source_ref is not declared: {source_ref!r}")

        status = event.get("status")
        if status not in ALLOWED_STATUS:
            raise TraceError(f"unsupported event status: {status!r}")
        exit_code = event.get("exit_code")
        if exit_code is not None and (
            not isinstance(exit_code, int) or isinstance(exit_code, bool)
        ):
            raise TraceError("exit_code must be integer or null")
        material_id = event.get("material_id")
        if material_id is not None and (
            not isinstance(material_id, str) or not material_id
        ):
            raise TraceError("material_id must be non-empty string or null")

        normalized.append(
            {
                "type": kind,
                "at": at,
                "source_ref": source_ref,
                "status": status,
                "exit_code": exit_code,
                "material_id": material_id,
            }
        )

    meta = {
        "rep_id": rep_id,
        "actor_family": actor_family,
        "trace_quality": trace_quality,
    }
    return meta, normalized


def reduce_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    meta, events = _load(manifest)
    types = Counter(event["type"] for event in events)

    dispatch = next((e for e in events if e["type"] == "DISPATCH"), None)
    first_admit = next((e for e in events if e["type"] == "PROVIDER_ADMIT"), None)
    first_reject = next((e for e in events if e["type"] == "PROVIDER_REJECT"), None)

    mutations = [e for e in events if e["type"] == "MUTATE"]
    feedbacks = [e for e in events if e["type"] == "FEEDBACK"]

    noop_mutations = 0
    prior_material: str | None = None
    for event in mutations:
        material = event["material_id"]
        if material is not None and prior_material is not None and material == prior_material:
            noop_mutations += 1
        if material is not None:
            prior_material = material

    feedback_results: list[dict[str, Any]] = []
    for feedback in feedbacks:
        preceding = [
            event
            for event in mutations
            if event["at"] <= feedback["at"] and event["material_id"] is not None
        ]
        baseline = preceding[-1]["material_id"] if preceding else None
        next_mutation = next(
            (event for event in mutations if event["at"] > feedback["at"]),
            None,
        )
        if next_mutation is None:
            disposition = "unknown-no-followup-mutation"
            latency = None
        elif baseline is None or next_mutation["material_id"] is None:
            disposition = "unknown-missing-material-identity"
            latency = _seconds(feedback["at"], next_mutation["at"])
        elif next_mutation["material_id"] == baseline:
            disposition = "no-material-adaptation"
            latency = _seconds(feedback["at"], next_mutation["at"])
        else:
            disposition = "material-adaptation"
            latency = _seconds(feedback["at"], next_mutation["at"])
        feedback_results.append(
            {
                "feedback_source_ref": feedback["source_ref"],
                "next_mutation_source_ref": (
                    next_mutation["source_ref"] if next_mutation else None
                ),
                "disposition": disposition,
                "seconds_to_next_mutation": latency,
            }
        )

    pre_execution_provider_failure = bool(
        first_reject
        and not first_admit
        and not any(
            event["type"]
            in {"PLAN", "MODEL_CALL", "TOOL_CALL", "TOOL_RESULT", "MUTATE"}
            for event in events
        )
    )

    tool_errors = sum(
        1
        for event in events
        if event["type"] == "TOOL_RESULT" and event["status"] == "error"
    )
    validation_failures = sum(
        1
        for event in events
        if event["type"] == "VALIDATE" and event["status"] == "fail"
    )
    clean_completions = [
        event
        for event in events
        if event["type"] == "COMPLETE"
        and (event["exit_code"] == 0 or event["status"] == "success")
    ]
    completion_validation_mismatch = bool(clean_completions and validation_failures)

    signals: list[str] = []
    if pre_execution_provider_failure:
        signals.append("PRE_EXECUTION_PROVIDER_FAILURE")
    if noop_mutations:
        signals.append("NOOP_MATERIAL_MUTATION")
    if any(
        result["disposition"] == "no-material-adaptation"
        for result in feedback_results
    ):
        signals.append("NO_MATERIAL_ADAPTATION_AFTER_FEEDBACK")
    if any(
        result["disposition"].startswith("unknown-")
        for result in feedback_results
    ):
        signals.append("UNKNOWN_FEEDBACK_ADAPTATION")
    if tool_errors and types["REPAIR"]:
        signals.append("TOOL_FAILURE_WITH_REPAIR")
    elif tool_errors:
        signals.append("TOOL_FAILURE")
    if completion_validation_mismatch:
        signals.append("COMPLETION_VALIDATION_MISMATCH")
    if meta["trace_quality"] == "censored":
        signals.append("CENSORED_TRACE")
    elif meta["trace_quality"] == "partial":
        signals.append("PARTIAL_TRACE")
    elif meta["trace_quality"] == "unknown":
        signals.append("UNKNOWN_TRACE_QUALITY")
    if types["UNKNOWN_GAP"]:
        signals.append("UNKNOWN_GAP_PRESENT")

    if meta["trace_quality"] == "censored":
        trace_disposition = "CENSORED"
    elif meta["trace_quality"] == "partial":
        trace_disposition = "PARTIAL"
    elif meta["trace_quality"] == "unknown":
        trace_disposition = "UNKNOWN"
    else:
        trace_disposition = "COMPLETE"

    return {
        "record_type": "retrospective-trajectory-result",
        "schema_version": 1,
        **meta,
        "trace_disposition": trace_disposition,
        "event_count": len(events),
        "event_type_counts": dict(sorted(types.items())),
        "provider_admit_count": types["PROVIDER_ADMIT"],
        "provider_reject_count": types["PROVIDER_REJECT"],
        "pre_execution_provider_failure": pre_execution_provider_failure,
        "mutation_count": len(mutations),
        "noop_mutation_count": noop_mutations,
        "feedback_results": feedback_results,
        "tool_error_count": tool_errors,
        "repair_count": types["REPAIR"],
        "validation_failure_count": validation_failures,
        "completion_validation_mismatch": completion_validation_mismatch,
        "unknown_gap_count": types["UNKNOWN_GAP"],
        "dispatch_to_first_admit_seconds": (
            _seconds(dispatch["at"], first_admit["at"])
            if dispatch and first_admit
            else None
        ),
        "dispatch_to_first_reject_seconds": (
            _seconds(dispatch["at"], first_reject["at"])
            if dispatch and first_reject
            else None
        ),
        "signals": sorted(set(signals)),
        "hidden_reasoning_inferred": False,
        "qualification_state_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = reduce_manifest(manifest)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
