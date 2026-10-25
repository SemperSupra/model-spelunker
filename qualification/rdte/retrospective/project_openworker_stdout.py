#!/usr/bin/env python3
"""Privacy-safe projection of OpenWorker's existing stdout telemetry.

RDT&E only: model-spelunker#114 / agent-dispatch-private#314.

Consumes stdout already emitted by qualification/adapters/openworker_projected.py.
Does not require OpenWorker source changes. Raw stdout is expected to remain
ephemeral and must not be uploaded by the calling workflow.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _canonical_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    )


def _numeric_mapping(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int | float] = {}
    for key, item in value.items():
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            out[str(key)] = item
    return out


def _tool_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            names.append(item)
            continue
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        function = function if isinstance(function, dict) else {}
        name = function.get("name") or item.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _safe_provider_observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "requested_model",
        "resolved_model",
        "provider",
        "system_fingerprint",
        "service_tier",
        "finish_reason",
        "request_message_bytes",
        "request_tool_schema_bytes",
        "output_text_bytes",
        "reasoning_bytes",
        "tool_argument_bytes",
        "client_wall_seconds",
        "first_event_seconds",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_tokens",
        "cache_write_tokens",
        "queue_time",
        "prompt_time",
        "completion_time",
        "provider_total_time",
        "provider_cost",
    }
    out: dict[str, Any] = {}
    for key in allowed:
        item = value.get(key)
        if item is None:
            continue
        if isinstance(item, (str, int, float)) and not isinstance(item, bool):
            out[key] = item
    generation = value.get("openrouter_generation")
    if isinstance(generation, dict):
        safe_generation = {
            key: item
            for key, item in generation.items()
            if isinstance(item, (str, int, float, bool)) or item is None
        }
        if safe_generation:
            out["openrouter_generation"] = safe_generation
    error = value.get("openrouter_generation_error")
    if isinstance(error, str):
        out["openrouter_generation_error"] = error
    return out


def project_stdout(stdout: str, *, source_ref: str | None = None) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    model_calls: list[dict[str, Any]] = []
    provider_observations: list[dict[str, Any]] = []
    final_usage: dict[str, int | float] = {}
    summary_projection: list[str] = []
    summary_event_counts: dict[str, int | float] = {}
    summary_tool_names: list[str] = []
    summary_target_exists: bool | None = None
    approval_count: int | None = None
    suppressed_batch_count: int | None = None
    malformed_prefixed_lines = 0
    ignored_lines = 0
    event_type_counts: Counter[str] = Counter()
    tool_name_counts: Counter[str] = Counter()

    for line_number, raw_line in enumerate(stdout.splitlines(), start=1):
        line = raw_line.strip()
        matched = False

        for prefix, kind in (
            ("OPENWORKER_EVENT=", "event"),
            ("MODEL_SPELUNKER_MODEL_CALL_STARTED=", "model_call"),
            ("MODEL_SPELUNKER_PROVIDER_OBSERVATIONS=", "provider_observations"),
            ("MODEL_SPELUNKER_USAGE=", "usage"),
            ("OPENWORKER_SUMMARY=", "summary"),
        ):
            if not line.startswith(prefix):
                continue
            matched = True
            payload_text = line[len(prefix):]
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError:
                malformed_prefixed_lines += 1
                break

            if kind == "event":
                if not isinstance(payload, dict):
                    break
                event_type = payload.get("type")
                event_type = event_type if isinstance(event_type, str) else "UNKNOWN"
                event_type_counts[event_type] += 1
                tool_names = _tool_names(payload.get("tool_calls"))
                for name in tool_names:
                    tool_name_counts[name] += 1
                event: dict[str, Any] = {
                    "sequence": len(events),
                    "source_line": line_number,
                    "type": event_type,
                    "tool_names": tool_names,
                    "payload_bytes": _canonical_bytes(payload),
                    "content_retained": False,
                }
                for key in ("status", "error_type", "iterations"):
                    value = payload.get(key)
                    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                        event[key] = value
                usage = _numeric_mapping(payload.get("usage"))
                if usage:
                    event["usage"] = usage
                if "error" in payload:
                    event["error_present"] = payload.get("error") is not None
                events.append(event)

            elif kind == "model_call":
                if not isinstance(payload, dict):
                    break
                call: dict[str, Any] = {
                    "index": payload.get("index")
                    if isinstance(payload.get("index"), int)
                    else len(model_calls) + 1,
                }
                for key in (
                    "requested_model",
                    "request_message_bytes",
                    "request_tool_schema_bytes",
                ):
                    value = payload.get(key)
                    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                        call[key] = value
                model_calls.append(call)

            elif kind == "provider_observations":
                if isinstance(payload, list):
                    provider_observations.extend(
                        item
                        for item in (_safe_provider_observation(row) for row in payload)
                        if item
                    )

            elif kind == "usage":
                final_usage = _numeric_mapping(payload)

            elif kind == "summary":
                if not isinstance(payload, dict):
                    break
                projection = payload.get("projection")
                if isinstance(projection, list):
                    summary_projection = [
                        item for item in projection if isinstance(item, str)
                    ]
                summary_event_counts = _numeric_mapping(payload.get("event_counts"))
                summary_tool_names = _tool_names(payload.get("tool_calls"))
                for name in summary_tool_names:
                    tool_name_counts[name] += 1
                if isinstance(payload.get("target_exists"), bool):
                    summary_target_exists = payload["target_exists"]
                if isinstance(payload.get("approval_count"), int):
                    approval_count = payload["approval_count"]
                suppressed = payload.get("suppressed_speculative_batches")
                if isinstance(suppressed, list):
                    suppressed_batch_count = len(suppressed)
            break

        if not matched:
            ignored_lines += 1

    source: dict[str, Any] = {
        "format": "openworker-native-stdout-markers",
        "stdout_bytes": len(stdout.encode("utf-8")),
        "malformed_prefixed_lines": malformed_prefixed_lines,
        "ignored_lines": ignored_lines,
        "raw_content_digest_retained": False,
    }
    if source_ref:
        source["restricted_source_ref"] = source_ref

    return {
        "record_type": "openworker-scientific-trace-projection",
        "schema_version": 1,
        "source": source,
        "summary": {
            "event_count": len(events),
            "event_type_counts": dict(sorted(event_type_counts.items())),
            "model_call_started_count": len(model_calls),
            "provider_observation_count": len(provider_observations),
            "tool_name_counts": dict(sorted(tool_name_counts.items())),
            "final_usage": final_usage,
            "projection": summary_projection,
            "adapter_event_counts": summary_event_counts,
            "adapter_tool_names": summary_tool_names,
            "target_exists": summary_target_exists,
            "approval_count": approval_count,
            "suppressed_speculative_batch_count": suppressed_batch_count,
            "hidden_reasoning_inferred": False,
            "sensitive_content_retained": False,
        },
        "model_calls": model_calls,
        "provider_observations": provider_observations,
        "events": events,
        "qualification_state_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stdout", type=Path)
    parser.add_argument("--source-ref", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = project_stdout(
        args.stdout.read_text(encoding="utf-8", errors="replace"),
        source_ref=args.source_ref or None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
