#!/usr/bin/env python3
"""Privacy-safe scientific projection of Goose stream-json.

Promoted optional science projector from Model Spelunker #112/#113 and agent-dispatch-private #314.

This projector consumes stdout that Goose already emits with
--output-format stream-json. It does not enable new Goose instrumentation,
does not retain prompt/reasoning/tool payload content, and makes no actor
qualification claim.

Privacy invariant:
- no raw prompt/text/thinking/tool arguments/tool results are retained;
- no public deterministic digest of those payloads is emitted;
- equality within one run is represented only by opaque, run-local classes.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


class _EquivalenceClasses:
    """Assign opaque run-local labels without exporting content-derived hashes."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self._classes: dict[bytes, str] = {}

    def label(self, value: Any) -> str:
        raw = _canonical_bytes(value)
        found = self._classes.get(raw)
        if found is not None:
            return found
        label = f"{self.prefix}{len(self._classes) + 1}"
        self._classes[raw] = label
        return label


def _payload_shape(value: Any) -> dict[str, Any]:
    raw = _canonical_bytes(value)
    if value is None:
        kind = "null"
        top_level_items = 0
    elif isinstance(value, dict):
        kind = "object"
        top_level_items = len(value)
    elif isinstance(value, list):
        kind = "array"
        top_level_items = len(value)
    elif isinstance(value, bool):
        kind = "boolean"
        top_level_items = None
    elif isinstance(value, (int, float)):
        kind = "number"
        top_level_items = None
    elif isinstance(value, str):
        kind = "string"
        top_level_items = None
    else:
        kind = type(value).__name__
        top_level_items = None
    out: dict[str, Any] = {
        "bytes": len(raw),
        "kind": kind,
        "content_retained": False,
    }
    if top_level_items is not None:
        out["top_level_items"] = top_level_items
    return out


def _numeric_usage(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int | float] = {}
    for key, item in value.items():
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)) and item >= 0:
            out[str(key)] = item
    return out


def _tool_request(
    block: dict[str, Any],
    call_classes: _EquivalenceClasses,
) -> dict[str, Any]:
    call = block.get("toolCall")
    call = call if isinstance(call, dict) else {}
    status = call.get("status")
    value = call.get("value")
    value = value if isinstance(value, dict) else {}

    name = value.get("name")
    if not isinstance(name, str) or not name:
        name = "UNKNOWN"

    arguments = value.get("arguments")
    if arguments is None:
        arguments = {}

    return {
        "kind": "tool_request",
        "id": block.get("id") if isinstance(block.get("id"), str) else None,
        "tool_name": name,
        "request_status": status if isinstance(status, str) else None,
        "arguments": _payload_shape(arguments),
        "call_equivalence_class": call_classes.label(
            {"tool_name": name, "arguments": arguments}
        ),
    }


def _tool_response(
    block: dict[str, Any],
    result_classes: _EquivalenceClasses,
) -> dict[str, Any]:
    result = block.get("toolResult")
    result = result if isinstance(result, dict) else {}
    status = result.get("status")
    if status == "success":
        payload = result.get("value")
    elif status == "error":
        payload = result.get("error")
    else:
        payload = result

    out = {
        "kind": "tool_response",
        "id": block.get("id") if isinstance(block.get("id"), str) else None,
        "response_status": status if isinstance(status, str) else None,
        "payload": _payload_shape(payload),
        "result_equivalence_class": result_classes.label(
            {"status": status, "payload": payload}
        ),
    }
    value = result.get("value")
    if isinstance(value, dict) and isinstance(value.get("isError"), bool):
        out["provider_is_error"] = value["isError"]
    return out


def project_stream(stdout: str, *, source_ref: str | None = None) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    malformed_json_lines = 0
    ignored_non_json_lines = 0
    content_types: Counter[str] = Counter()
    call_classes = _EquivalenceClasses("call-")
    result_classes = _EquivalenceClasses("result-")
    call_class_counts: Counter[str] = Counter()
    assistant_message_ids: set[str] = set()
    anonymous_assistant_events = 0
    inference_message_ids: set[str] = set()
    anonymous_inference_events = 0
    complete: dict[str, Any] | None = None

    for line_number, raw_line in enumerate(stdout.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("{"):
            ignored_non_json_lines += 1
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            malformed_json_lines += 1
            continue
        if not isinstance(obj, dict):
            continue

        event_type = obj.get("type")
        if event_type == "message":
            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            message_id = message.get("id")
            created = message.get("created")
            metadata = message.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            inference = metadata.get("inference")
            inference = inference if isinstance(inference, dict) else {}

            event: dict[str, Any] = {
                "sequence": len(events),
                "source_line": line_number,
                "type": "message",
                "message_id": message_id if isinstance(message_id, str) else None,
                "role": role if isinstance(role, str) else None,
                "created": created
                if isinstance(created, int) and not isinstance(created, bool)
                else None,
                "content": [],
            }

            provider = inference.get("provider")
            requested = inference.get("requestedModel")
            has_inference = False
            if isinstance(provider, str) and provider:
                event["provider"] = provider
                has_inference = True
            if isinstance(requested, str) and requested:
                event["requested_model"] = requested
                has_inference = True

            usage = _numeric_usage(metadata.get("usage"))
            if usage:
                event["usage"] = usage

            if role == "assistant":
                if isinstance(message_id, str) and message_id:
                    assistant_message_ids.add(message_id)
                else:
                    anonymous_assistant_events += 1
            if has_inference:
                if isinstance(message_id, str) and message_id:
                    inference_message_ids.add(message_id)
                else:
                    anonymous_inference_events += 1

            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    if not isinstance(block_type, str):
                        block_type = "unknown"
                    content_types[block_type] += 1

                    if block_type == "toolRequest":
                        projected = _tool_request(block, call_classes)
                        call_class_counts[projected["call_equivalence_class"]] += 1
                    elif block_type == "toolResponse":
                        projected = _tool_response(block, result_classes)
                    elif block_type == "text":
                        text = block.get("text")
                        encoded = text.encode("utf-8") if isinstance(text, str) else b""
                        projected = {
                            "kind": "text",
                            "bytes": len(encoded),
                            "content_retained": False,
                        }
                    elif block_type in {"thinking", "redactedThinking"}:
                        projected = {
                            "kind": block_type,
                            "content_retained": False,
                        }
                    elif block_type == "error":
                        projected = {
                            "kind": "error",
                            "content_retained": False,
                        }
                    else:
                        projected = {
                            "kind": block_type,
                            "content_retained": False,
                        }
                    event["content"].append(projected)
            events.append(event)

        elif event_type == "notification":
            events.append(
                {
                    "sequence": len(events),
                    "source_line": line_number,
                    "type": "notification",
                    "extension_id": obj.get("extension_id")
                    if isinstance(obj.get("extension_id"), str)
                    else None,
                }
            )
        elif event_type == "error":
            error = obj.get("error")
            events.append(
                {
                    "sequence": len(events),
                    "source_line": line_number,
                    "type": "error",
                    "error": _payload_shape(error),
                }
            )
        elif event_type == "complete":
            complete = {
                key: value
                for key, value in obj.items()
                if key != "type"
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value >= 0
            }
            events.append(
                {
                    "sequence": len(events),
                    "source_line": line_number,
                    "type": "complete",
                }
            )
        else:
            events.append(
                {
                    "sequence": len(events),
                    "source_line": line_number,
                    "type": str(event_type)
                    if event_type is not None
                    else "unknown",
                }
            )

    tool_requests = sum(
        1
        for event in events
        for item in event.get("content", [])
        if item.get("kind") == "tool_request"
    )
    tool_responses = sum(
        1
        for event in events
        for item in event.get("content", [])
        if item.get("kind") == "tool_response"
    )
    tool_errors = sum(
        1
        for event in events
        for item in event.get("content", [])
        if item.get("kind") == "tool_response"
        and (
            item.get("response_status") == "error"
            or item.get("provider_is_error") is True
        )
    )
    repeated_tool_calls = sum(
        max(0, count - 1) for count in call_class_counts.values()
    )

    source: dict[str, Any] = {
        "format": "goose-stream-json",
        "stdout_bytes": len(stdout.encode("utf-8")),
        "raw_content_digest_retained": False,
        "malformed_json_lines": malformed_json_lines,
        "ignored_non_json_lines": ignored_non_json_lines,
    }
    if source_ref:
        source["restricted_source_ref"] = source_ref

    return {
        "record_type": "goose-scientific-trace-projection",
        "schema_version": 2,
        "source": source,
        "summary": {
            "event_count": len(events),
            "message_event_count": sum(
                1 for event in events if event["type"] == "message"
            ),
            "assistant_message_groups": (
                len(assistant_message_ids) + anonymous_assistant_events
            ),
            "inference_metadata_message_groups": (
                len(inference_message_ids) + anonymous_inference_events
            ),
            "model_call_count": None,
            "model_call_count_reason": (
                "Goose message groups are observable; one group is not asserted "
                "to equal one provider model call."
            ),
            "tool_request_count": tool_requests,
            "tool_response_count": tool_responses,
            "tool_error_count": tool_errors,
            "repeated_identical_tool_call_count": repeated_tool_calls,
            "content_type_counts": dict(sorted(content_types.items())),
            "complete_usage": complete,
            "hidden_reasoning_inferred": False,
            "sensitive_content_retained": False,
        },
        "events": events,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stream", type=Path)
    parser.add_argument("--source-ref", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    projection = project_stream(
        args.stream.read_text(encoding="utf-8", errors="replace"),
        source_ref=args.source_ref or None,
    )
    rendered = json.dumps(projection, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
