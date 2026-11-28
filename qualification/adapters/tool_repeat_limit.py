"""Task-local, opt-in limit on identical projected tool-call attempts."""

from __future__ import annotations

from collections import Counter
import json
from typing import Any, Iterable, Mapping


ENVIRONMENT_KEY = "MODEL_SPELUNKER_TOOL_REPEAT_LIMIT"


class ToolRepeatLimitError(RuntimeError):
    """A terminal policy outcome; its message contains only a fixed reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _json_value(value: Any) -> None:
    """Reject coercions such as tuple-to-array or non-string object keys."""
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("non-JSON object key")
            _json_value(item)
    elif type(value) is list:
        for item in value:
            _json_value(item)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ValueError("non-JSON value")


def _canonical_arguments(arguments: Any) -> str:
    if type(arguments) is not dict:
        raise ValueError("tool arguments must be a JSON object")
    _json_value(arguments)
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ToolRepeatLimit:
    """Count whole effective batches only; unknown tools keep native denial.

    Counts are total attempts for one projected name and canonical argument
    object over the task, not consecutive runs or semantically equivalent paths.
    The private signatures never appear in the bounded rejection record.
    """

    def __init__(self, limit: int, projected_names: Iterable[str]) -> None:
        if type(limit) is not int or not 0 <= limit <= 24:
            raise ValueError(f"{ENVIRONMENT_KEY} must be an integer from 0 to 24")
        self.limit = limit
        self.projected_names = frozenset(projected_names)
        self._counts: Counter[tuple[str, str]] = Counter()
        self.rejection: dict[str, Any] | None = None

    @classmethod
    def from_environment(
        cls, projected_names: Iterable[str], environ: Mapping[str, str]
    ) -> ToolRepeatLimit:
        raw = environ.get(ENVIRONMENT_KEY, "0")
        if raw not in {str(value) for value in range(25)}:
            raise ValueError(f"{ENVIRONMENT_KEY} must be an integer from 0 to 24")
        return cls(int(raw), projected_names)

    def ensure_open(self) -> None:
        if self.rejection is not None:
            raise ToolRepeatLimitError(self.rejection["error_type"])

    def _reject(self, reason: str, call_index: int) -> None:
        if self.rejection is None:
            self.rejection = {"error_type": reason, "call_index": call_index}
        self.ensure_open()

    def check(self, calls: Iterable[Any], *, call_index: int) -> None:
        self.ensure_open()
        if self.limit == 0:
            return
        pending: Counter[tuple[str, str]] = Counter()
        for call in calls:
            name = call.name
            if type(name) is not str or name not in self.projected_names:
                continue
            try:
                signature = (name, _canonical_arguments(call.arguments))
            except (TypeError, ValueError, RecursionError):
                self._reject("REPEAT_LIMIT_INVALID_ARGUMENTS", call_index)
            pending[signature] += 1
            if self._counts[signature] + pending[signature] > self.limit:
                self._reject("REPEAT_LIMIT_EXCEEDED", call_index)
        # Nothing is dispatched, and no part is counted, until the entire
        # effective batch passes. A refusal permanently closes this task gate.
        self._counts.update(pending)
