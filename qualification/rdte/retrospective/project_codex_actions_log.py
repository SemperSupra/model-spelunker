#!/usr/bin/env python3
"""Privacy-safe projection of retained Codex GitHub Actions diagnostics.

RDT&E only: model-spelunker#114 / agent-dispatch-private#314.

The raw Actions log is an ephemeral input. This projector retains only bounded
process/resource facts and never emits prompts, tool arguments, model text, or
the raw log.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def _json_after(prefix: str, line: str) -> Any | None:
    marker = line.find(prefix)
    if marker < 0:
        return None
    payload = line[marker + len(prefix) :].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def project_log(text: str, *, source_ref: str) -> dict[str, Any]:
    stderr_signals: list[dict[str, Any]] = []
    provider_requests: list[dict[str, Any]] = []
    candidate_exit = None
    verifier_exit = None
    max_rss_kbytes = None

    for line in text.splitlines():
        signals = _json_after("CODEX_STDERR_SIGNALS=", line)
        if isinstance(signals, list):
            stderr_signals.extend(
                item for item in signals if isinstance(item, dict)
            )

        request = _json_after("OLLAMA_REQUEST_SUMMARY=", line)
        if isinstance(request, dict):
            provider_requests.append(request)

        match = re.search(r"DIAG_CANDIDATE_RC=(-?\d+)", line)
        if match:
            candidate_exit = int(match.group(1))
        match = re.search(r"DIAG_VERIFIER_RC=(-?\d+)", line)
        if match:
            verifier_exit = int(match.group(1))
        match = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", line)
        if match:
            max_rss_kbytes = int(match.group(1))

    session_ids: set[str] = set()
    models: set[str] = set()
    providers: set[str] = set()
    reasoning_efforts: set[str] = set()
    tool_names: Counter[str] = Counter()
    function_call_items = 0
    message_items = 0
    tool_errors = 0
    tool_completed = 0
    process_events: list[dict[str, Any]] = []

    for item in stderr_signals:
        raw = item.get("line")
        if not isinstance(raw, str):
            continue
        t_rel = item.get("t_rel_s")
        event: dict[str, Any] | None = None

        session = re.search(
            r"session_id: SessionId \{ uuid: ([0-9a-fA-F-]+) \}.*?"
            r'model: "([^"]+)".*?model_provider_id: "([^"]+)"',
            raw,
        )
        if session:
            session_ids.add(session.group(1))
            models.add(session.group(2))
            providers.add(session.group(3))
            event = {"kind": "session_configured"}

        effort = re.search(r"codex\.turn\.reasoning_effort=([^}:\s]+)", raw)
        if effort:
            reasoning_efforts.add(effort.group(1))

        if 'item_type="function_call"' in raw:
            function_call_items += 1
            event = {"kind": "function_call_output"}

        tool = re.search(r"ToolCall:\s*([A-Za-z0-9_.:-]+)", raw)
        if tool:
            name = tool.group(1)
            tool_names[name] += 1
            event = {"kind": "tool_call", "tool_name": name}

        if "failed to parse function arguments" in raw:
            tool_errors += 1
            event = {"kind": "tool_argument_error"}

        if 'event.name="codex.tool_call"' in raw and "tool call completed" in raw:
            tool_completed += 1
            event = {"kind": "tool_call_completed"}

        if 'item_type="message"' in raw:
            message_items += 1
            event = {"kind": "message_output"}

        if event is not None:
            if isinstance(t_rel, (int, float)) and not isinstance(t_rel, bool):
                event["t_rel_s"] = t_rel
            process_events.append(event)

    provider_projection = []
    for request in provider_requests:
        projected = {}
        for key in (
            "model",
            "body_bytes",
            "input_bytes",
            "input_items",
            "instructions_chars",
            "max_output_tokens",
            "tool_count",
            "temperature",
            "top_p",
        ):
            value = request.get(key)
            if isinstance(value, (str, int, float)) or value is None:
                projected[key] = value
        reasoning = request.get("reasoning")
        if isinstance(reasoning, dict):
            effort = reasoning.get("effort")
            if isinstance(effort, str):
                projected["reasoning_effort"] = effort
        provider_projection.append(projected)

    completion_validation_mismatch = bool(
        candidate_exit == 0 and verifier_exit not in (None, 0)
    )

    return {
        "record_type": "codex-actions-trace-projection",
        "schema_version": 1,
        "source_ref": source_ref,
        "summary": {
            "session_count": len(session_ids),
            "models": sorted(models),
            "providers": sorted(providers),
            "reasoning_efforts": sorted(reasoning_efforts),
            "stderr_signal_count": len(stderr_signals),
            "function_call_output_count": function_call_items,
            "tool_call_count": sum(tool_names.values()),
            "tool_name_counts": dict(sorted(tool_names.items())),
            "tool_argument_error_count": tool_errors,
            "tool_call_completed_count": tool_completed,
            "message_output_count": message_items,
            "provider_request_count": len(provider_projection),
            "candidate_exit_code": candidate_exit,
            "verifier_exit_code": verifier_exit,
            "completion_validation_mismatch": completion_validation_mismatch,
            "max_rss_kbytes": max_rss_kbytes,
            "raw_content_retained": False,
            "hidden_reasoning_inferred": False,
        },
        "provider_requests": provider_projection,
        "process_events": process_events,
        "qualification_state_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = project_log(
        args.log.read_text(encoding="utf-8", errors="replace"),
        source_ref=args.source_ref,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
