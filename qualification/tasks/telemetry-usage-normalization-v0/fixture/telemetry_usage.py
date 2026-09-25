"""Project Model Spelunker receipt observations into Agent Dispatch usage tuples."""

from __future__ import annotations

from typing import Any


def project_usage(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized usage records without inventing missing measurements."""
    raise NotImplementedError
