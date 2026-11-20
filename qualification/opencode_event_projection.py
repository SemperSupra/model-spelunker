#!/usr/bin/env python3
"""Privacy-minimizing OpenCode V2 JSONL event evidence projection.

Source-side observation only: no execution, network or inference. Raw event
payloads are NEVER emitted. Independent candidate/validator evidence remains
required before an actor outcome can be called successful.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import BinaryIO

MAX_EVENT_BYTES = 262_144
MAX_STREAM_BYTES = 8_388_608
MAX_EVENTS = 20_000

# V2 names documented at https://opencode.ai/docs/api . Unknown event
# names are counted without echoing user-controlled labels.
ALLOWED_TYPES = frozenset({
    "session.created", "session.model.selected", "session.execution.started",
    "session.execution.succeeded", "session.execution.failed",
    "session.execution.interrupted", "session.usage.updated",
    "session.step.started", "session.step.ended", "session.step.failed",
    "session.tool.called", "session.tool.success", "session.tool.failed",
    "session.retry.scheduled", "session.compaction.started",
    "session.compaction.ended", "session.compaction.failed",
    "session.skill.activated", "permission.asked", "permission.replied",
    "filesystem.changed", "worktree.updated", "config.updated",
    "plugin.updated", "session.idle", "V2Event.server.connected",
})
TERMINAL_TYPES = {
    "session.execution.succeeded": "SUCCEEDED_MARKER",
    "session.execution.failed": "FAILED_MARKER",
    "session.execution.interrupted": "INTERRUPTED_MARKER",
}


class ProjectionError(ValueError):
    """Only fixed, non-sensitive messages may be surfaced to callers."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProjectionError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise ProjectionError("non-finite JSON number")


def _decode(raw: bytes) -> dict[str, object]:
    try:
        obj = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ProjectionError("malformed JSONL event") from None
    if not isinstance(obj, dict):
        raise ProjectionError("event must be a JSON object")
    if not isinstance(obj.get("type"), str) or not obj["type"]:
        raise ProjectionError("event type missing or invalid")
    if "properties" in obj and not isinstance(obj["properties"], dict):
        raise ProjectionError("event properties must be a JSON object")
    return obj


def project_events(input_stream: BinaryIO) -> dict[str, object]:
    """Bounded, stream-oriented reduction. Never returns untrusted strings."""
    digest = hashlib.sha256()
    by_type: Counter[str] = Counter()
    unknown = 0
    events = 0
    total_bytes = 0
    identities: set[str] = set()
    missing_session_identity = 0
    terminal_count = 0
    terminal_kind = "NONE"

    while True:
        raw = input_stream.readline(MAX_EVENT_BYTES + 2)
        if not raw:
            break
        if len(raw) > MAX_EVENT_BYTES:
            raise ProjectionError("event size limit exceeded")
        total_bytes += len(raw)
        if total_bytes > MAX_STREAM_BYTES:
            raise ProjectionError("stream size limit exceeded")
        events += 1
        if events > MAX_EVENTS:
            raise ProjectionError("event count limit exceeded")
        if not raw.strip():
            raise ProjectionError("blank JSONL record")
        digest.update(raw)
        item = _decode(raw)
        typ = item["type"]
        properties = item.get("properties", {})
        if typ in ALLOWED_TYPES:
            by_type[typ] += 1
        else:
            unknown += 1
        if typ.startswith("session."):
            sid = properties.get("sessionID")
            if not isinstance(sid, str) or not sid or len(sid) > 128:
                missing_session_identity += 1
            else:
                identities.add(sid)  # only in memory; never returned
                if len(identities) > 1:
                    raise ProjectionError("multiple session identities in one stream")
        if typ in TERMINAL_TYPES:
            terminal_count += 1
            terminal_kind = TERMINAL_TYPES[typ]

    if events == 0:
        raise ProjectionError("empty event stream")
    if terminal_count > 1:
        terminal_kind = "AMBIGUOUS_MULTIPLE_MARKERS"

    return {
        "projection": "opencode-v2-event-counts-v1",
        "evidence_status": "ADVISORY_UNAUTHENTICATED_NOT_TASK_VERIFIED",
        "stream_completeness": "UNKNOWN_NO_REPLAY_OR_SEQUENCE_PROOF",
        "session_identity": (
            "ONE_UNVERIFIED_DECLARED_SESSION" if identities and not missing_session_identity
            else "INCOMPLETE_OR_UNVERIFIED"
        ),
        "reported_terminal_marker": terminal_kind,
        "event_count": events,
        "event_bytes": total_bytes,
        "input_sha256": "sha256:" + digest.hexdigest(),
        "known_event_counts": dict(sorted(by_type.items())),
        "unknown_event_count": unknown,
        "missing_session_identity_events": missing_session_identity,
        "model_identity": "NOT_ATTESTED_FROM_EVENTS",
        "independent_verifier": "NOT_RUN_BY_THIS_TOOL",
        "promotion_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="V2 JSONL captured from an authorized workcell")
    args = parser.parse_args(argv)
    try:
        with args.input.open("rb") as stream:
            projected = project_events(stream)
    except (ProjectionError, OSError) as exc:
        # Path, raw payload and OSError exception messages may contain host data.
        code = "INVALID_EVENT_STREAM" if isinstance(exc, ProjectionError) else "INPUT_UNAVAILABLE"
        print(code, file=sys.stderr)
        return 2
    print(json.dumps(projected, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
