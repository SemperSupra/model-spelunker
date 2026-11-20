#!/usr/bin/env python3
"""Read-only, source-bound consumer of Governance #227 dle-context-v1.

This is an experimental advisory bootstrap. It does not authenticate GitHub,
reconcile claims, publish context or grant rights.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "dle-context-v1"
MAX_CONTEXT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 6 * 1024
MAX_FIELD_CHARS = 2048
MAX_CLAIMS = 16
MAX_LIST_ITEMS = 24


def _valid_text(value: Any, label: str, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > MAX_FIELD_CHARS:
        raise ValueError(f"invalid {label}")
    if required and not value.strip():
        raise ValueError(f"empty {label}")
    if "\x00" in value or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"control character in {label}")
    return value


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise ValueError(f"invalid {label}")
    return [_valid_text(item, label) for item in value]


def _read_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("context must be a regular non-symlink file")
    if path.stat().st_size > MAX_CONTEXT_BYTES:
        raise ValueError("context too large")
    with path.open("rb") as handle:
        data = handle.read(MAX_CONTEXT_BYTES + 1)
    if not 1 <= len(data) <= MAX_CONTEXT_BYTES:
        raise ValueError("context exceeds byte limit")
    return data


def project_context(
    path: Path,
    *,
    expected_authority: str,
    expected_revision: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Bind advisory output to an independently supplied DLE digest/revision.

    The SHA binds the underlying DLE snapshot, not this projection's file.
    Source authentication cannot be asserted by this local consumer.
    """
    source = _valid_text(expected_authority, "expected authority")
    revision = _valid_text(expected_revision, "expected revision")
    expected = _valid_text(expected_sha256, "expected DLE sha256").lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("invalid expected source digest")
    data = _read_regular(path)
    try:
        body = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid context JSON") from exc
    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        raise ValueError("unsupported context schema")
    if body.get("authority") != source or body.get("revision") != revision:
        raise ValueError("stale or wrong DLE authority/revision")
    if not isinstance(body.get("sha256"), str) or body["sha256"].lower() != expected:
        raise ValueError("stale or wrong DLE digest")
    if body.get("github_verified") is not False:
        raise ValueError("unexpected source-verification assertion")
    mission = _valid_text(body.get("mission"), "mission")
    next_action = _valid_text(body.get("next_action"), "next action")
    constraints = _strings(body.get("constraints"), "constraints")
    unknowns = _strings(body.get("unknowns"), "unknowns")
    claims = body.get("accepted")
    if not isinstance(claims, list) or len(claims) > MAX_CLAIMS:
        raise ValueError("invalid accepted claims")
    accepted = []
    seen = set()
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("status") != "accepted":
            raise ValueError("unaccepted claim in context accepted list")
        cid = _valid_text(claim.get("id"), "claim id")
        if cid in seen:
            raise ValueError("duplicate accepted claim id")
        seen.add(cid)
        accepted.append({
            "id": cid,
            "text": _valid_text(claim.get("text"), "claim text"),
            "source": _valid_text(claim.get("source"), "claim source"),
        })
    result = {
        "schema": "dle-bootstrap-advisory-v1",
        "authority": source,
        "revision": revision,
        "authority_sha256": expected,
        "projection_file_sha256": hashlib.sha256(data).hexdigest(),
        "github_verified": False,
        "advisory_only": True,
        "mission": mission,
        "next_action": next_action,
        "constraints": constraints,
        "unknowns": unknowns,
        "accepted": sorted(accepted, key=lambda c: c["id"]),
    }
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("bounded bootstrap output exceeded")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Produce a bounded advisory bootstrap")
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    try:
        result = project_context(
            args.context, expected_authority=args.authority,
            expected_revision=args.revision, expected_sha256=args.sha256
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, "DLE_BOOTSTRAP_UNKNOWN: " + str(exc) + "\n")
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
