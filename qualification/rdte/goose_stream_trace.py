#!/usr/bin/env python3
"""Privacy-safe scientific projection of Goose stream-json.

RDT&E only: SemperSupra/model-spelunker#112 / agent-dispatch-private#314.

This reducer consumes stdout that Goose already emits with
--output-format stream-json. It does not enable new Goose instrumentation,
does not retain prompt/reasoning/tool payload content, and makes no actor
qualification claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _payload_summary(value: Any) -> dict[str, Any]:
    data = _canonical_bytes(value)
    return {
        "bytes": len(data),
        "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
    }


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


def _tool_request(block: dict[str, Any]) -> dict[str, Any]:
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

    signature = {"name": name, "arguments": arguments}
    return {
        "kind": "tool_request",
        "id": block.get("id") if isinstance(block.get("id"), str) else None,
        "tool_name": name,
        "request_status": status if isinstance(status, str) else None,
        "arguments": _payload_summary(arguments),
        "signature_sha256": _digest(signature),
    }


def _tool_response(block: dict[str, Any]) -> dict[str, Any]:
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
        "payload": _payload_summary(payload),
    }
    value = result.get("value")
    if isinstance(value, dict) and isinstance(value.get("isError"), bool):
        out["provider_is_error"] = value["isError"]
    return out


def project_stream(stdout: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    malformed_json_lines = 0
    ignored_non_json_lines = 0
    content_types: Counter[str] = Counter()
    tool_signatures: Counter[str] = Counter()
    assistant_message_ids: set[str] = set()
    anonymous_assistant_events = 0
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
                "created": created if isinstance(created, int) and not isinstance(created, bool) else None,
                "content": [],
            }

            provider = inference.get("provider")
            requested = inference.get("requestedModel")
            if isinstance(provider, str) and provider:
                event["provider"] = provider
            if isinstance(requested, str) and requested:
                event["requested_model"] = requested

            usage = _numeric_usage(metadata.get("usage"))
            if usage:
                event["usage"] = usage

            if role == "assistant":
                if isinstance(message_id, str) and message_id:
                    assistant_message_ids.add(message_id)
                else:
                    anonymous_assistant_events += 1

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
                        projected = _tool_request(block)
                        signature = projected["signature_sha256"]
                        tool_signatures[signature] += 1
                    elif block_type == "toolResponse":
                        projected = _tool_response(block)
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
            events.append({
                "sequence": len(events),
                "source_line": line_number,
                "type": "notification",
                "extension_id": obj.get("extension_id") if isinstance(obj.get("extension_id"), str) else None,
            })
        elif event_type == "error":
            error = obj.get("error")
            events.append({
                "sequence": len(events),
                "source_line": line_number,
                "type": "error",
                "error": _payload_summary(error),
                "content_retained": False,
            })
        elif event_type == "complete":
            complete = {
                key: value
                for key, value in obj.items()
                if key != "type"
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value >= 0
            }
            events.append({
                "sequence": len(events),
                "source_line": line_number,
                "type": "complete",
            })
        else:
            events.append({
                "sequence": len(events),
                "source_line": line_number,
                "type": str(event_type) if event_type is not None else "unknown",
            })

    tool_requests = sum(1 for event in events for item in event.get("content", []) if item.get("kind") == "tool_request")
    tool_responses = sum(1 for event in events for item in event.get("content", []) if item.get("kind") == "tool_response")
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
    repeated_tool_calls = sum(max(0, count - 1) for count in tool_signatures.values())

    return {
        "record_type": "goose-scientific-trace-projection",
        "schema_version": 1,
        "source": {
            "format": "goose-stream-json",
            "stdout_bytes": len(stdout.encode("utf-8")),
            "stdout_sha256": "sha256:" + hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "malformed_json_lines": malformed_json_lines,
            "ignored_non_json_lines": ignored_non_json_lines,
        },
        "summary": {
            "event_count": len(events),
            "message_event_count": sum(1 for e in events if e["type"] == "message"),
            "assistant_model_rounds": len(assistant_message_ids) + anonymous_assistant_events,
            "tool_request_count": tool_requests,
            "tool_response_count": tool_responses,
            "tool_error_count": tool_errors,
            "repeated_identical_tool_call_count": repeated_tool_calls,
            "content_type_counts": dict(sorted(content_types.items())),
            "complete_usage": complete,
            "hidden_reasoning_inferred": False,
        },
        "events": events,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stream", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    projection = project_stream(args.stream.read_text(encoding="utf-8", errors="replace"))
    rendered = json.dumps(projection, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
