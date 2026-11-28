"""Bounded, content-free observations of native OpenWorker tool results.

TOOL_FINISHED is the authority for result order/name/status, not unique calls.
The pinned engine supplies an exception class only through its audit sink. Use
it only for a started tool when exactly one finished audit immediately precedes
its matching event. Missing, repeated, intervening, or mismatched observations
remain unknown.
"""

from __future__ import annotations

from typing import Any, Iterable


RESULT_LIMIT = 24  # Adapter's maximum declared iteration budget; never expanded.
STATUSES = frozenset({"ok", "error", "denied", "interrupted"})
# Never publish an arbitrary exception class name: user code can choose one.
ERROR_TYPES = frozenset({
    "FileNotFoundError", "PermissionError", "IsADirectoryError",
    "NotADirectoryError", "OSError", "TypeError", "ValueError", "KeyError",
    "RuntimeError", "TimeoutError", "UnicodeDecodeError",
})


class ToolResultObserver:
    def __init__(self, projected_names: Iterable[str]) -> None:
        self.projected_names = frozenset(projected_names)
        self.results: list[dict[str, Any]] = []
        self.event_count = 0
        self.finished_audit_count = 0
        self._pending_count = 0
        self._pending: tuple[str, str, str] | None = None
        self._started_tool: str | None = None

    @staticmethod
    def _allowed(value: Any, allowed: frozenset[str]) -> str:
        return value if isinstance(value, str) and value in allowed else "unknown"

    def audit(self, payload: Any) -> None:
        """Project native audit fields immediately; retain no raw payload."""
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("stage") != "finished":
            self._pending_count = 0
            self._pending = None
            return
        self.finished_audit_count += 1
        self._pending_count = min(self._pending_count + 1, 2)
        result = payload.get("result")
        error_type = self._allowed(
            result.get("error_type") if isinstance(result, dict) else None,
            ERROR_TYPES,
        )
        self._pending = (
            self._allowed(payload.get("tool"), self.projected_names),
            self._allowed(payload.get("status"), STATUSES),
            error_type,
        ) if self._pending_count == 1 else None

    def observe_event(self, event_type: str, payload: Any) -> None:
        payload = payload if isinstance(payload, dict) else {}
        pending, pending_count = self._pending, self._pending_count
        self._pending = None
        self._pending_count = 0
        started_tool = self._started_tool
        self._started_tool = None
        if event_type == "EventType.TOOL_STARTED":
            self._started_tool = self._allowed(payload.get("name"), self.projected_names)
            return
        if event_type != "EventType.TOOL_FINISHED":
            return
        self.event_count += 1
        if len(self.results) >= RESULT_LIMIT:
            return
        name = self._allowed(payload.get("name"), self.projected_names)
        status = self._allowed(payload.get("status"), STATUSES)
        error_type = "unknown"
        if (pending_count == 1 and pending is not None
                and name != "unknown" and started_tool == name and status == "error"
                and pending[:2] == (name, status)):
            error_type = pending[2]
        self.results.append({
            "index": self.event_count,
            "tool": name,
            "status": status,
            "error_type": error_type,
        })

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": "openworker-tool-results-v1",
            "limit": RESULT_LIMIT,
            "event_count": self.event_count,
            "finished_audit_count": self.finished_audit_count,
            "omitted_count": self.event_count - len(self.results),
            "results": [dict(row) for row in self.results],
        }
