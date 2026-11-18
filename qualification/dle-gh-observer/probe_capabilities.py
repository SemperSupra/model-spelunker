#!/usr/bin/env python3
"""Version-specific, read-only gh capability discovery. Help ≠ operational admission."""
from __future__ import annotations

import json
import subprocess

CAPABILITIES = {
    "native_issue_artifacts": (["gh", "issue", "artifact", "--help"], None),
    "native_repo_read_file": (["gh", "repo", "read-file", "--help"], None),
    "native_repo_read_dir": (["gh", "repo", "read-dir", "--help"], None),
    "native_issue_worktree": (["gh", "issue", "develop", "--help"], "--worktree"),
    "native_pr_worktree": (["gh", "pr", "checkout", "--help"], "--worktree"),
    "native_event_subscriptions": (["gh", "event", "subscription", "--help"], None),
    "native_issue_json": (["gh", "issue", "view", "--help"], "--json"),
}

def default_run(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(
            args, capture_output=True, text=True, timeout=6, check=False
        )
        return p.returncode, p.stdout[:16384]
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""

def classify(run=default_run) -> dict[str, object]:
    status, version = run(["gh", "--version"])
    result: dict[str, object] = {
        "schema": "gh-native-capability-census-v0",
        "gh_version": version.splitlines()[0] if status == 0 and version else "UNKNOWN",
        "basis": "local_help_only_not_end_to_end_qualification",
        "capabilities": {},
        "mutation_performed": False,
    }
    for name, (args, marker) in sorted(CAPABILITIES.items()):
        rc, output = run(args)
        result["capabilities"][name] = (
            "HELP_EXPOSED" if rc == 0 and (marker is None or marker in output)
            else "UNAVAILABLE_OR_UNKNOWN"
        )
    return result

if __name__ == "__main__":
    print(json.dumps(classify(), sort_keys=True))
