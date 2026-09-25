"""Project Model Spelunker receipt observations into Agent Dispatch usage tuples."""

from __future__ import annotations

import math
from typing import Any

# Ordered projection spec: (path, kind, unit, source).
# The output order follows this exact sequence.
_FIELD_SPECS: tuple[tuple[tuple[str, ...], str, str, str], ...] = (
    (("observation", "wall_seconds"), "elapsed-time", "seconds", "observed"),
    (
        ("observation", "workload", "model_calls_started"),
        "model-calls-started",
        "calls",
        "observed",
    ),
    (
        ("observation", "workload", "model_calls_completed"),
        "model-calls-completed",
        "calls",
        "observed",
    ),
    (
        ("observation", "workload", "tool_calls_started"),
        "tool-calls-started",
        "calls",
        "observed",
    ),
    (
        ("observation", "workload", "tool_calls_completed"),
        "tool-calls-completed",
        "calls",
        "observed",
    ),
    (("observation", "input_tokens"), "input-tokens", "tokens", "authoritative"),
    (("observation", "output_tokens"), "output-tokens", "tokens", "authoritative"),
    (
        ("observation", "cache_read_tokens"),
        "cache-read-tokens",
        "tokens",
        "authoritative",
    ),
    (
        ("observation", "cache_write_tokens"),
        "cache-write-tokens",
        "tokens",
        "authoritative",
    ),
    (("observation", "cost"), "cost", "usd", "authoritative"),
    (
        ("observation", "human_interventions"),
        "human-interventions",
        "count",
        "observed",
    ),
    (
        ("observation", "workload", "client_wall_seconds_total"),
        "model-client-wall-time",
        "seconds",
        "observed",
    ),
    (
        ("observation", "workload", "request_message_bytes_total"),
        "request-message-bytes",
        "bytes",
        "derived",
    ),
    (
        ("observation", "workload", "request_tool_schema_bytes_total"),
        "request-tool-schema-bytes",
        "bytes",
        "derived",
    ),
    (
        ("observation", "workload", "output_text_bytes_total"),
        "output-text-bytes",
        "bytes",
        "derived",
    ),
    (
        ("observation", "workload", "reasoning_bytes_total"),
        "reasoning-bytes",
        "bytes",
        "derived",
    ),
    (
        ("observation", "workload", "tool_argument_bytes_total"),
        "tool-argument-bytes",
        "bytes",
        "derived",
    ),
)


def _lookup(receipt: Any, path: tuple[str, ...]) -> Any:
    """Walk ``path`` through nested mappings.

    A missing key, or a non-mapping encountered before the end of the path,
    means the value is missing (distinct from an explicit null).
    """
    current: Any = receipt
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return current


class _Missing:
    """Sentinel marking a field that is absent from the receipt."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<MISSING>"


_MISSING = _Missing()


def _is_valid_number(value: Any) -> bool:
    """Return True for finite, non-negative numbers that are not booleans."""
    # ``bool`` is a subclass of ``int``; booleans are explicitly invalid.
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False  # NaN and +/-inf are invalid.
    return value >= 0


def project_usage(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized usage records without inventing missing measurements.

    Missing or ``None`` fields are omitted; explicit numeric zeros are kept.
    Booleans, negative numbers, non-numbers, NaN and infinities are omitted.
    The input ``receipt`` is never mutated.
    """
    if not isinstance(receipt, dict):
        return []

    records: list[dict[str, Any]] = []
    for path, kind, unit, source in _FIELD_SPECS:
        value = _lookup(receipt, path)
        if value is _MISSING or value is None:
            continue
        if not _is_valid_number(value):
            continue
        records.append(
            {
                "kind": kind,
                "value": value,
                "unit": unit,
                "source": source,
            }
        )
    return records
