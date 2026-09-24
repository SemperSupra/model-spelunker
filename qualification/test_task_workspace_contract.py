#!/usr/bin/env python3
"""Fail closed when a qualification task assumes the wrong actor workspace layout."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "qualification" / "tasks"

# These packages were observed before the layout defect was discovered.
# They remain immutable historical evidence and MUST NOT become executable in place.
KNOWN_INVALID_TREE_SHA = {
    "api-boundary-classification-v0": "8a5e07c6a068f8f9bd6245880f7d106d5ca46da4",
    "method-ir-siglip2-b16-256-v0": "0fac23c92a49f1330a57e5dd0a7d115312e99700",
}

ROOT_FIXTURE_RE = re.compile(r"""\broot\s*/\s*["']fixture(?:["']|/)""")


def git_tree_sha(task_id: str) -> str:
    rel = f"qualification/tasks/{task_id}"
    return subprocess.check_output(
        ["git", "rev-parse", f"HEAD:{rel}"],
        cwd=ROOT,
        text=True,
    ).strip()


def workspace_violations(task_dir: Path) -> list[str]:
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    fixture_dir = task_dir / task["fixture"]
    if not fixture_dir.is_dir():
        return [f"fixture directory missing: {fixture_dir}"]

    actor_root_names = {p.name for p in fixture_dir.iterdir()}
    instruction = str(task.get("instruction") or "")
    verifier = (task_dir / task["verifier"]).read_text(encoding="utf-8")
    violations: list[str] = []

    # run_task.py copies fixture-directory CONTENTS into workspace root.
    # A literal fixture/... path is valid only if the source fixture itself
    # contains a top-level directory named fixture.
    if "fixture/" in instruction and "fixture" not in actor_root_names:
        violations.append(
            "instruction references fixture/... but canonical actor workspace is flattened"
        )
    if ROOT_FIXTURE_RE.search(verifier) and "fixture" not in actor_root_names:
        violations.append(
            "verifier reads root/fixture/... but canonical verifier workspace is flattened"
        )

    return violations


def check_catalog() -> None:
    seen = set()
    for task_dir in sorted(p for p in TASKS.iterdir() if p.is_dir()):
        task_id = task_dir.name
        seen.add(task_id)
        violations = workspace_violations(task_dir)

        if task_id in KNOWN_INVALID_TREE_SHA:
            actual = git_tree_sha(task_id)
            expected = KNOWN_INVALID_TREE_SHA[task_id]
            assert actual == expected, (
                f"frozen invalid task {task_id} changed: {actual} != {expected}; "
                "mint a new task version instead"
            )
            assert violations, (
                f"known-invalid package {task_id} unexpectedly became layout-valid in place; "
                "do not repair observed task versions"
            )
            print(f"KNOWN_INVALID {task_id} tree={actual}: {'; '.join(violations)}")
            continue

        assert not violations, f"{task_id}: {'; '.join(violations)}"

    missing = set(KNOWN_INVALID_TREE_SHA) - seen
    assert not missing, f"frozen invalid task packages disappeared: {sorted(missing)}"


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="task-layout-contract-") as tmp:
        root = Path(tmp)

        bad = root / "bad"
        (bad / "fixture").mkdir(parents=True)
        (bad / "fixture" / "evidence.json").write_text("{}\n", encoding="utf-8")
        (bad / "task.json").write_text(
            json.dumps(
                {
                    "fixture": "fixture",
                    "verifier": "verify.py",
                    "instruction": "Inspect fixture/evidence.json and write out.json.",
                }
            ),
            encoding="utf-8",
        )
        (bad / "verify.py").write_text(
            'from pathlib import Path\ndef check(root: Path):\n    return (root / "fixture" / "evidence.json").is_file()\n',
            encoding="utf-8",
        )
        violations = workspace_violations(bad)
        assert len(violations) == 2, violations

        good = root / "good"
        (good / "fixture").mkdir(parents=True)
        (good / "fixture" / "evidence.json").write_text("{}\n", encoding="utf-8")
        (good / "task.json").write_text(
            json.dumps(
                {
                    "fixture": "fixture",
                    "verifier": "verify.py",
                    "instruction": "Inspect evidence.json and write out.json.",
                }
            ),
            encoding="utf-8",
        )
        (good / "verify.py").write_text(
            'from pathlib import Path\ndef check(root: Path):\n    return (root / "evidence.json").is_file()\n',
            encoding="utf-8",
        )
        assert workspace_violations(good) == []


if __name__ == "__main__":
    self_test()
    check_catalog()
    print("PASS qualification task workspace-layout contract")
