#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from run_task import validate_task_workspace_layout

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
TASKS = ROOT / "tasks"
HISTORICAL_INVALID_TREE_SHA = {
    "api-boundary-classification-v0": "8a5e07c6a068f8f9bd6245880f7d106d5ca46da4",
    "method-ir-siglip2-b16-256-v0": "0fac23c92a49f1330a57e5dd0a7d115312e99700",
}
ROOT_FIXTURE_RE = re.compile(r"""\broot\s*/\s*["']fixture(?:["']|/)""")


def git_tree_sha(task_id: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", f"HEAD:qualification/tasks/{task_id}"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def verifier_layout_violation(task_dir: Path, task: dict[str, object]) -> bool:
    fixture = str(task["fixture"])
    fixture_dir = task_dir / fixture
    root_names = {p.name for p in fixture_dir.iterdir()}
    verifier = (task_dir / str(task["verifier"])).read_text(encoding="utf-8")
    return bool(ROOT_FIXTURE_RE.search(verifier) and fixture not in root_names)


class TaskWorkspaceLayoutTests(unittest.TestCase):
    def test_catalog_rejects_only_exact_preserved_historical_invalid_packages(self):
        observed_invalid = set()
        for task_dir in sorted(p for p in TASKS.iterdir() if p.is_dir()):
            task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
            instruction_invalid = False
            try:
                validate_task_workspace_layout(task_dir, task)
            except ValueError:
                instruction_invalid = True
            verifier_invalid = verifier_layout_violation(task_dir, task)
            if instruction_invalid or verifier_invalid:
                observed_invalid.add(task_dir.name)

        self.assertEqual(observed_invalid, set(HISTORICAL_INVALID_TREE_SHA))
        for task_id, expected_sha in HISTORICAL_INVALID_TREE_SHA.items():
            self.assertEqual(
                git_tree_sha(task_id),
                expected_sha,
                f"historical invalid task {task_id} changed in place; mint a new task version instead",
            )

    def test_fixture_prefix_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            (task_dir / "fixture").mkdir()
            task = {
                "fixture": "fixture",
                "instruction": "Read fixture/evidence.json and write result.json.",
                "allowed_write_paths": ["result.json"],
            }
            with self.assertRaisesRegex(ValueError, "non-existent workspace path"):
                validate_task_workspace_layout(task_dir, task)

    def test_root_visible_fixture_contents_are_admitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            (task_dir / "fixture").mkdir()
            task = {
                "fixture": "fixture",
                "instruction": "Read evidence.json and write result.json.",
                "allowed_write_paths": ["result.json"],
            }
            validate_task_workspace_layout(task_dir, task)

    def test_verifier_nested_fixture_assumption_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            (task_dir / "fixture").mkdir()
            (task_dir / "verify.py").write_text(
                'from pathlib import Path\ndef check(root: Path):\n    return (root / "fixture" / "evidence.json").is_file()\n',
                encoding="utf-8",
            )
            task = {
                "fixture": "fixture",
                "verifier": "verify.py",
                "instruction": "Read evidence.json.",
                "allowed_write_paths": ["result.json"],
            }
            self.assertTrue(verifier_layout_violation(task_dir, task))

    def test_api_boundary_v1_accepts_canonical_flattened_workspace(self):
        task_dir = TASKS / "api-boundary-classification-v1"
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location(
            "api_boundary_v1_verify", task_dir / str(task["verifier"])
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            shutil.copytree(task_dir / str(task["fixture"]), work)
            self.assertTrue((work / "evidence.json").is_file())
            self.assertFalse((work / "fixture").exists())
            (work / "classification.json").write_text(
                json.dumps(module.good_output(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.assertTrue(module.check(work))


if __name__ == "__main__":
    unittest.main()
