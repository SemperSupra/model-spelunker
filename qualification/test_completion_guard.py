#!/usr/bin/env python3
"""Independent contracts for bounded, presence-only completion feedback."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qualification.adapters.completion_guard import CompletionGuard, REQUIRED_FILES_V1


class CompletionGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="completion-guard-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def make_guard(self, paths=("result.json",), *, allowed=None, tools=None):
        return CompletionGuard.from_environment(
            {
                "MODEL_SPELUNKER_COMPLETION_CHECK": REQUIRED_FILES_V1,
                "MODEL_SPELUNKER_REQUIRED_OUTPUT_PATHS": json.dumps(list(paths)),
            },
            self.root,
            allowed if allowed is not None else {self.root / path for path in paths},
            tools if tools is not None else {"read_file", "write_file"},
        )

    @staticmethod
    def stop(guard, **overrides):
        values = {
            "event_type": "EventType.ASSISTANT_MESSAGE",
            "payload": {"tool_calls": []},
            "observations": [{"finish_reason": "stop"}],
            "calls_started": 1,
            "call_limit": 4,
        }
        values.update(overrides)
        return guard.observe(**values)

    def test_disabled_never_resolves_or_checks_paths(self):
        # Even an invalid declaration must be inert until explicitly opted in.
        with mock.patch.object(Path, "resolve", side_effect=AssertionError("path resolution")), \
             mock.patch.object(Path, "lstat", side_effect=AssertionError("filesystem read")), \
             mock.patch.object(Path, "open", side_effect=AssertionError("content read")):
            guard = CompletionGuard.from_environment(
                {"MODEL_SPELUNKER_REQUIRED_OUTPUT_PATHS": "not JSON"},
                Path("unresolved-workspace"), set(), set(),
            )
            before = guard.summary()
            self.assertIsNone(self.stop(guard))
            self.assertIsNone(self.stop(guard, event_type="EventType.ERROR"))
            self.assertEqual(guard.summary(), before)

    def test_required_outputs_are_explicit_not_inferred_from_write_scope(self):
        for raw in (None, "", "[]", "null", '{}', '["result.json", "result.json"]', '[1]'):
            with self.subTest(raw=raw):
                env = {"MODEL_SPELUNKER_COMPLETION_CHECK": REQUIRED_FILES_V1}
                if raw is not None:
                    env["MODEL_SPELUNKER_REQUIRED_OUTPUT_PATHS"] = raw
                with self.assertRaises(ValueError):
                    CompletionGuard.from_environment(
                        env, self.root, {self.root / "result.json"}, {"write_file"}
                    )
        with self.assertRaises(ValueError):
            self.make_guard(allowed={self.root / "other.json"})
        with self.assertRaises(ValueError):
            self.make_guard(tools={"read_file"})
        with self.assertRaises(ValueError):
            CompletionGuard.from_environment(
                {"MODEL_SPELUNKER_COMPLETION_CHECK": "automatic"}, self.root, set(), set()
            )

    def test_unsafe_relative_spellings_and_absolute_paths_are_rejected(self):
        for path in ("", ".", "../outside", "a/../result.json", "/tmp/result.json",
                     "./result.json", "a//result.json", "a/./result.json", "result.json/",
                     "C:/result.json", "a\\result.json", "bad\x00name", "bad\nname"):
            with self.subTest(path=repr(path)), self.assertRaises(ValueError):
                self.make_guard((path,))

    def test_links_and_nonregular_targets_are_rejected_before_following(self):
        target = self.root / "result.json"
        target.symlink_to(target)  # A loop previously escaped as RuntimeError.
        with self.assertRaises(ValueError):
            self.make_guard()
        target.unlink()
        with tempfile.TemporaryDirectory(prefix="guard-external-") as other:
            (self.root / "linked").symlink_to(other, target_is_directory=True)
            with self.assertRaises(ValueError):
                self.make_guard(("linked/output.json",))
        (self.root / "directory").mkdir()
        with self.assertRaises(ValueError):
            self.make_guard(("directory",))
        (self.root / "parent").write_text("not a directory")
        with self.assertRaises(ValueError):
            self.make_guard(("parent/output.json",))

    def test_wrong_existing_contents_are_not_read_or_judged(self):
        output = self.root / "result.json"
        output.write_text("this is deliberately invalid JSON")
        with mock.patch.object(Path, "open", side_effect=AssertionError("oracle leak")):
            guard = self.make_guard()
            self.assertIsNone(self.stop(guard))
        self.assertEqual(guard.summary()["nudges"], 0)

    def test_missing_output_nudges_once_without_revealing_any_answer(self):
        guard = self.make_guard(("subdir/result.json", "other.json"))
        message = self.stop(guard)
        self.assertIn('"subdir/result.json"', message)
        self.assertIn('"other.json"', message)
        self.assertIn("existing tools and permissions", message)
        self.assertNotIn("entrypoint", message)
        self.assertNotIn("scripts/validate.py", message)
        self.assertIsNone(self.stop(guard, observations=[{"finish_reason": "stop"}] * 2,
                                    calls_started=2))
        self.assertEqual(guard.summary()["nudges"], 1)
        self.assertEqual(guard.summary()["missing_at_nudge"], 2)

    def test_only_a_current_completed_no_tool_response_can_trigger(self):
        cases = (
            {"event_type": "EventType.TURN_END"},
            {"payload": {}},
            {"payload": {"tool_calls": ["read_file"]}},
            {"observations": []},
            {"observations": [{"finish_reason": "stop"}], "calls_started": 2},
            {"observations": [{"finish_reason": "length"}]},
            {"observations": [{"finish_reason": "tool_calls"}]},
            {"observations": [{}]},
            {"calls_started": True},
            {"call_limit": True},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                guard = self.make_guard()
                with mock.patch.object(guard, "_file_state", side_effect=AssertionError("early I/O")):
                    self.assertIsNone(self.stop(guard, **arguments))
                self.assertEqual(guard.nudges, 0)

    def test_errors_denials_interruption_and_protocol_faults_remain_blocked(self):
        cases = (
            ("EventType.ERROR", {}, False),
            ("EventType.INTERRUPTED", {}, False),
            ("EventType.TOOL_FINISHED", {"status": "denied"}, False),
            ("EventType.TOOL_FINISHED", {"status": "error"}, False),
            ("EventType.ASSISTANT_MESSAGE", {"tool_calls": []}, True),
        )
        for event, payload, protocol_fault in cases:
            with self.subTest(event=event, payload=payload, protocol_fault=protocol_fault):
                guard = self.make_guard()
                self.assertIsNone(self.stop(guard, event_type=event, payload=payload,
                                            protocol_fault=protocol_fault))
                self.assertIsNone(self.stop(guard))
                self.assertIsNotNone(guard.summary()["blocked_reason"])
                self.assertEqual(guard.nudges, 0)

    def test_exhausted_budget_cannot_be_refreshed_by_later_feedback(self):
        guard = self.make_guard()
        self.assertIsNone(self.stop(guard, calls_started=4,
                                    observations=[{"finish_reason": "stop"}] * 4))
        self.assertEqual(guard.summary()["blocked_reason"], "call_budget_exhausted")
        self.assertIsNone(self.stop(guard))
        self.assertEqual(guard.nudges, 0)

    def test_output_replaced_by_link_after_admission_disables_feedback(self):
        guard = self.make_guard()
        (self.root / "result.json").symlink_to(self.root / "outside-output")
        self.assertIsNone(self.stop(guard))
        self.assertEqual(guard.summary()["blocked_reason"], "output_path_unsafe")


if __name__ == "__main__":
    unittest.main()
