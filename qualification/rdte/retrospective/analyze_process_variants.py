#!/usr/bin/env python3
"""Bounded cross-family process-variant feasibility analysis.

RDT&E only: model-spelunker#114 / agent-dispatch-private#314.

This deliberately does NOT claim a universal agent event ontology. It preserves
native event vocabularies per harness and computes:
- native event sequences;
- run-length-compressed variants;
- native directly-follows counts;
- a small conservative common-anchor projection only where event semantics are
  explicit in the retained trace.

It does not rank actors, infer hidden reasoning, or update qualification state.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _rle(sequence: list[str]) -> list[dict[str, Any]]:
    if not sequence:
        return []
    out: list[dict[str, Any]] = []
    current = sequence[0]
    count = 1
    for item in sequence[1:]:
        if item == current:
            count += 1
            continue
        out.append({"event": current, "count": count})
        current = item
        count = 1
    out.append({"event": current, "count": count})
    return out


def _dfg(sequence: list[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for left, right in zip(sequence, sequence[1:]):
        counts[f"{left} -> {right}"] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _goose(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    native: list[str] = []
    anchors: list[str] = []
    tool_names: set[str] = set()

    # Goose stream-json emits repeated chunks for the same message id. Those
    # are transport/streaming records, not independent process steps. Collapse
    # contiguous chunks into one message group and preserve the first-seen
    # content-kind set/order within that group.
    current_key: tuple[str, str] | None = None
    current_role: str | None = None
    current_kinds: list[str] = []
    current_kind_set: set[str] = set()

    def flush_group() -> None:
        nonlocal current_key, current_role, current_kinds, current_kind_set
        if current_key is None:
            return
        kinds = "+".join(current_kinds) if current_kinds else "empty"
        native.append(f"message_group:{current_role or 'unknown'}:{kinds}")
        current_key = None
        current_role = None
        current_kinds = []
        current_kind_set = set()

    anonymous_index = 0
    for event in data.get("events", []):
        if not isinstance(event, dict):
            continue
        etype = str(event.get("type") or "unknown")
        if etype != "message":
            flush_group()
            native.append(etype)
            if etype == "complete":
                anchors.append("COMPLETE")
            elif etype == "error":
                anchors.append("ERROR")
            continue

        role = event.get("role")
        role = role if isinstance(role, str) else "unknown"
        message_id = event.get("message_id")
        if isinstance(message_id, str) and message_id:
            key = (role, message_id)
        else:
            # Anonymous chunks cannot safely be merged across records because
            # there is no identity proving they belong to the same message.
            anonymous_index += 1
            key = (role, f"anonymous-{anonymous_index}")

        if current_key != key:
            flush_group()
            current_key = key
            current_role = role

        content = event.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "unknown")
            if kind not in current_kind_set:
                current_kind_set.add(kind)
                current_kinds.append(kind)

            if kind == "tool_request":
                anchors.append("TOOL_REQUEST")
                name = item.get("tool_name")
                if isinstance(name, str):
                    tool_names.add(name)
            elif kind == "tool_response":
                anchors.append("TOOL_RESULT")
                if (
                    item.get("response_status") == "error"
                    or item.get("provider_is_error") is True
                ):
                    anchors.append("ERROR")
            elif kind == "error":
                anchors.append("ERROR")

    flush_group()

    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    return {
        "family": "goose",
        "native_sequence": native,
        "anchor_sequence": anchors,
        "source_event_count": summary.get("event_count"),
        "message_group_count": len([
            token for token in native if token.startswith("message_group:")
        ]),
        "native_token_count": len(native),
        "anchor_count": len(anchors),
        "tool_names": sorted(tool_names),
    }


def _openworker(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    native: list[str] = []
    anchors: list[str] = []
    tool_names: set[str] = set()

    for event in data.get("events", []):
        if not isinstance(event, dict):
            continue
        etype = str(event.get("type") or "UNKNOWN")
        native.append(etype)
        upper = etype.upper()

        names = event.get("tool_names")
        if isinstance(names, list):
            tool_names.update(str(name) for name in names if isinstance(name, str))

        if "TOOL" in upper and (
            "PROPOSE" in upper or "CALL" in upper or "REQUEST" in upper
        ):
            anchors.append("TOOL_REQUEST")
        if "TOOL" in upper and (
            "RESULT" in upper
            or "RESPONSE" in upper
            or "COMPLETE" in upper
            or "FINISH" in upper
        ):
            anchors.append("TOOL_RESULT")
        if "ERROR" in upper or event.get("error_present") is True:
            anchors.append("ERROR")
        if "COMPLETE" in upper and "TOOL" not in upper:
            anchors.append("COMPLETE")

    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    return {
        "family": "openworker",
        "native_sequence": native,
        "anchor_sequence": anchors,
        "source_event_count": summary.get("event_count"),
        "native_token_count": len(native),
        "anchor_count": len(anchors),
        "tool_names": sorted(tool_names),
        "model_call_started_count": summary.get("model_call_started_count"),
        "provider_observation_count": summary.get("provider_observation_count"),
    }


def _codex(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    native: list[str] = []
    anchors: list[str] = []
    tool_names: set[str] = set()

    for event in data.get("process_events", []):
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "unknown")
        native.append(kind)
        name = event.get("tool_name")
        if isinstance(name, str):
            tool_names.add(name)

        if kind == "tool_call":
            anchors.append("TOOL_REQUEST")
        elif kind in {"tool_call_completed"}:
            anchors.append("TOOL_RESULT")
        elif "error" in kind:
            anchors.append("ERROR")

    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    if summary.get("completion_validation_mismatch") is True:
        anchors.append("VALIDATION_MISMATCH")

    return {
        "family": "codex",
        "native_sequence": native,
        "anchor_sequence": anchors,
        "source_event_count": len(data.get("process_events") or []),
        "native_token_count": len(native),
        "anchor_count": len(anchors),
        "tool_names": sorted(tool_names),
        "provider_request_count": summary.get("provider_request_count"),
        "completion_validation_mismatch": summary.get("completion_validation_mismatch"),
    }


def _finish(row: dict[str, Any]) -> dict[str, Any]:
    native = row.pop("native_sequence")
    anchors = row.pop("anchor_sequence")
    row["native_variant_rle"] = _rle(native)
    row["native_directly_follows"] = _dfg(native)
    row["anchor_variant"] = anchors
    row["anchor_directly_follows"] = _dfg(anchors)
    row["anchor_coverage"] = (
        round(len(anchors) / len(native), 4) if native else 0.0
    )
    return row


def analyze(
    goose_path: Path,
    openworker_path: Path,
    codex_paths: list[Path],
) -> dict[str, Any]:
    families = [_finish(_goose(goose_path)), _finish(_openworker(openworker_path))]
    for path in codex_paths:
        families.append(_finish(_codex(path)))

    anchor_vocabulary = sorted({
        anchor
        for family in families
        for anchor in family.get("anchor_variant", [])
    })
    anchor_family_counts: Counter[str] = Counter()
    for family in families:
        for anchor in set(family.get("anchor_variant", [])):
            anchor_family_counts[anchor] += 1
    shared_anchors = sorted(
        anchor for anchor, count in anchor_family_counts.items() if count >= 2
    )
    family_anchor_sets = {
        family["family"] + (
            f":{index}" if family["family"] == "codex" else ""
        ): sorted(set(family.get("anchor_variant", [])))
        for index, family in enumerate(families, start=1)
    }

    return {
        "record_type": "cross-family-process-variant-feasibility",
        "schema_version": 1,
        "family_count": len(families),
        "families": families,
        "anchor_vocabulary": anchor_vocabulary,
        "anchors_observed_in_multiple_families": shared_anchors,
        "anchor_family_counts": dict(sorted(anchor_family_counts.items())),
        "family_anchor_sets": family_anchor_sets,
        "interpretation": {
            "native_vocabularies_preserved": True,
            "universal_event_ontology_claimed": False,
            "conformance_model_built": False,
            "hidden_reasoning_inferred": False,
            "qualification_state_changed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goose", type=Path, required=True)
    parser.add_argument("--openworker", type=Path, required=True)
    parser.add_argument("--codex", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = analyze(args.goose, args.openworker, args.codex)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "family_count": result["family_count"],
        "anchor_vocabulary": result["anchor_vocabulary"],
        "anchors_observed_in_multiple_families": result["anchors_observed_in_multiple_families"],
        "families": [
            {
                "family": row["family"],
                "source_event_count": row.get("source_event_count"),
                "native_token_count": row["native_token_count"],
                "anchor_count": row["anchor_count"],
                "anchor_coverage": row["anchor_coverage"],
                "tool_names": row.get("tool_names", []),
                "anchor_variant": row["anchor_variant"],
            }
            for row in result["families"]
        ],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
