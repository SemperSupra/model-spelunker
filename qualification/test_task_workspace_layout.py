#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from run_task import validate_task_workspace_layout

ROOT = Path(__file__).resolve().parent
TASKS = ROOT / "tasks"
HISTORICAL_INVALID = {
    "api-boundary-classification-v0",
    "method-ir-siglip2-b16-256-v0",
}


class TaskWorkspaceLayoutTests(unittest.TestCase):
    def test_catalog_rejects_only_preserved_historical_invalid_packages(self):
        observed_invalid = set()
        for task_dir in sorted(p for p in TASKS.iterdir() if p.is_dir()):
            task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
            try:
                validate_task_workspace_layout(task_dir, task)
            except ValueError:
                observed_invalid.add(task_dir.name)
        self.assertEqual(observed_invalid, HISTORICAL_INVALID)

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


if __name__ == "__main__":
    unittest.main()
