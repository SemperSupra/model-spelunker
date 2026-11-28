"""Opt-in, bounded file-presence feedback for the existing OpenWorker loop.

This is not a task verifier. It sees only explicitly required output paths,
never expected contents, and cannot expand the tools, writes or turn budget.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Mapping


NONE = "none"
REQUIRED_FILES_V1 = "required-files-v1"


class CompletionGuard:
    def __init__(
        self, mode: str, workspace: Path, required_paths: tuple[str, ...] = ()
    ) -> None:
        self.mode = mode
        self.workspace = workspace
        self.required_paths = required_paths
        self.nudges = 0
        self.blocked_reason: str | None = None
        self.missing_at_nudge = 0

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
        workspace: Path,
        allowed_targets: set[Path],
        projected_tools: set[str],
    ) -> "CompletionGuard":
        mode = environ.get("MODEL_SPELUNKER_COMPLETION_CHECK", NONE)
        if mode == NONE:
            # An absent opt-in never changes historical behavior or reads files.
            return cls(mode, workspace)
        if mode != REQUIRED_FILES_V1:
            raise ValueError("COMPLETION_CHECK_MODE_INVALID")
        root = workspace.resolve()
        try:
            paths = json.loads(environ.get("MODEL_SPELUNKER_REQUIRED_OUTPUT_PATHS", ""))
        except (ValueError, TypeError):
            raise ValueError("COMPLETION_REQUIRED_OUTPUTS_INVALID") from None
        if (
            not isinstance(paths, list)
            or not 1 <= len(paths) <= 16
            or any(not isinstance(path, str) for path in paths)
            or len(set(paths)) != len(paths)
        ):
            raise ValueError("COMPLETION_REQUIRED_OUTPUTS_INVALID")
        if "write_file" not in projected_tools:
            raise ValueError("COMPLETION_WRITE_TOOL_REQUIRED")
        for path in paths:
            relative = PurePosixPath(path)
            if (
                not path
                or len(path) > 512
                or any(ord(char) < 32 or ord(char) == 127 for char in path)
                or "\\" in path
                or ":" in path
                or relative.is_absolute()
                or any(part in {".", ".."} for part in relative.parts)
                or relative.as_posix() != path
                or path == "."
            ):
                raise ValueError("COMPLETION_OUTPUT_PATH_INVALID")
        guard = cls(mode, root, tuple(sorted(paths)))
        # Do not follow a link or inspect an external target, even if it resolves
        # to a path in the write allowlist. Errors contain no local identifiers.
        for path in guard.required_paths:
            if guard._file_state(path) == "unsafe":
                raise ValueError("COMPLETION_OUTPUT_PATH_UNSAFE")
            # Safe canonical relative paths under a resolved root need no
            # further resolution. In particular, never resolve an output link.
            if root.joinpath(*PurePosixPath(path).parts) not in allowed_targets:
                raise ValueError("COMPLETION_OUTPUT_OUTSIDE_WRITE_SCOPE")
        return guard

    def _file_state(self, relative: str) -> str:
        current = self.workspace
        parts = PurePosixPath(relative).parts
        for index, part in enumerate(parts):
            current = current / part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                return "missing"
            except OSError:
                return "unsafe"
            if stat.S_ISLNK(mode):
                return "unsafe"
            if index < len(parts) - 1:
                if not stat.S_ISDIR(mode):
                    return "unsafe"
            elif not stat.S_ISREG(mode):
                return "unsafe"
        return "present"

    def observe(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        observations: list[dict[str, Any]],
        calls_started: int,
        call_limit: int,
        protocol_fault: bool = False,
    ) -> str | None:
        """Return at most one steering message, before the engine's stop check.

        The adapter queues it on the *current* TurnEngine.run generator; it must
        not start another run or reset max_iterations. Counts and metadata are
        kept even when the independent task verifier later rejects the output.
        """
        if self.mode == NONE:
            return None
        if event_type in {"EventType.ERROR", "EventType.INTERRUPTED"}:
            self.blocked_reason = "engine_error_or_interruption"
        elif event_type == "EventType.TOOL_FINISHED" and payload.get("status") != "ok":
            self.blocked_reason = "tool_not_successful"
        if protocol_fault:
            self.blocked_reason = "tool_protocol_fault"
        if self.blocked_reason or self.nudges or event_type != "EventType.ASSISTANT_MESSAGE":
            return None
        calls = payload.get("tool_calls")
        if not isinstance(calls, list) or calls:
            return None
        # A failed/incomplete call must not inherit an older stop observation.
        if (
            type(calls_started) is not int
            or type(call_limit) is not int
            or calls_started < 1
            or len(observations) != calls_started
            or observations[-1].get("finish_reason") != "stop"
        ):
            return None
        if calls_started >= call_limit:
            self.blocked_reason = "call_budget_exhausted"
            return None
        states = {path: self._file_state(path) for path in self.required_paths}
        if "unsafe" in states.values():
            self.blocked_reason = "output_path_unsafe"
            return None
        missing = [path for path, state in states.items() if state == "missing"]
        if not missing:
            return None
        self.nudges = 1
        self.missing_at_nudge = len(missing)
        return (
            "Harness completion check: these explicitly required output files "
            "are still missing: " + json.dumps(missing) + ". "
            "Continue the original task using the existing tools and permissions. "
            "Inspect the relevant evidence and create the required output; do not "
            "merely describe it or invent its contents. If blocked, report the blocker. "
            "The original task and total call budget remain unchanged."
        )

    def summary(self) -> dict[str, Any]:
        declaration = json.dumps(list(self.required_paths), separators=(",", ":"))
        return {
            "mode": self.mode,
            "required_output_count": len(self.required_paths),
            "requirements_sha256": "sha256:" + hashlib.sha256(declaration.encode()).hexdigest(),
            "nudges": self.nudges,
            "missing_at_nudge": self.missing_at_nudge,
            "blocked_reason": self.blocked_reason,
        }
