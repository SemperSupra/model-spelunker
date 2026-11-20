#!/usr/bin/env python3
"""Adversarial source-only tests; no model, OpenCode binary, or network."""

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest

try:
    from qualification.opencode_event_projection import (
        MAX_EVENT_BYTES, MAX_EVENTS, MAX_STREAM_BYTES, ProjectionError, main, project_events,
    )
except ImportError:
    from opencode_event_projection import (
        MAX_EVENT_BYTES, MAX_EVENTS, MAX_STREAM_BYTES, ProjectionError, main, project_events,
    )


SECRET = "SYNTHETIC_SECRET_DO_NOT_PROJECT_72390"
PRIVATE = "C:/private/owner/ssh/secret.txt"


def event(typ, sid="test-session", **properties):
    props = {"sessionID": sid, **properties} if sid is not None else properties
    return {"type": typ, "properties": props}


def events(*records):
    return io.BytesIO(b"".join((json.dumps(obj).encode("utf-8") + b"\n") for obj in records))


class ProjectionTests(unittest.TestCase):
    def assert_reject(self, raw):
        with self.assertRaises(ProjectionError):
            project_events(io.BytesIO(raw))

    def test_bounded_success_is_not_task_success(self):
        rows = events(
            event("session.execution.started"),
            event("session.tool.called", args={"command": PRIVATE, "token": SECRET}),
            event("session.tool.failed", error=SECRET),
            event("session.retry.scheduled", reason=PRIVATE),
            event("session.execution.succeeded", text=SECRET),
        )
        projected = project_events(rows)
        out = json.dumps(projected)
        self.assertEqual(projected["reported_terminal_marker"], "SUCCEEDED_MARKER")
        self.assertEqual(projected["known_event_counts"]["session.tool.failed"], 1)
        self.assertEqual(projected["event_count"], 5)
        self.assertEqual(projected["independent_verifier"], "NOT_RUN_BY_THIS_TOOL")
        self.assertFalse(projected["promotion_allowed"])
        self.assertNotIn(SECRET, out)
        self.assertNotIn(PRIVATE, out)
        self.assertNotIn("test-session", out)

    def test_absent_terminal_is_unknown(self):
        p = project_events(events(event("session.tool.called")))
        self.assertEqual(p["reported_terminal_marker"], "NONE")
        self.assertIn("UNKNOWN", p["stream_completeness"])

    def test_explicit_failure_is_not_validated_task_failure(self):
        p = project_events(events(event("session.execution.failed")))
        self.assertEqual(p["reported_terminal_marker"], "FAILED_MARKER")
        self.assertIn("NOT_TASK_VERIFIED", p["evidence_status"])

    def test_interrupt(self):
        p = project_events(events(event("session.execution.interrupted")))
        self.assertEqual(p["reported_terminal_marker"], "INTERRUPTED_MARKER")

    def test_ambiguous_terminal_does_not_choose_success(self):
        p = project_events(events(event("session.execution.succeeded"), event("session.execution.failed")))
        self.assertEqual(p["reported_terminal_marker"], "AMBIGUOUS_MULTIPLE_MARKERS")

    def test_mixed_session_ids_rejected(self):
        self.assert_reject(events(event("session.execution.started", sid="one"), event("session.execution.failed", sid="two")).getvalue())

    def test_missing_identity_is_unknown(self):
        p = project_events(events(event("session.execution.started", sid=None)))
        self.assertEqual(p["session_identity"], "INCOMPLETE_OR_UNVERIFIED")
        self.assertEqual(p["missing_session_identity_events"], 1)

    def test_unknown_event_label_is_not_quoted(self):
        p = project_events(events(event("user-secret-" + SECRET)))
        self.assertEqual(p["unknown_event_count"], 1)
        self.assertNotIn(SECRET, json.dumps(p))

    def test_reject_duplicate_nested_keys(self):
        self.assert_reject(b'{"type":"session.tool.called","properties":{"sessionID":"a","token":1,"token":2}}\n')

    def test_reject_duplicate_top_keys(self):
        self.assert_reject(b'{"type":"session.tool.called","type":"session.tool.success"}\n')

    def test_reject_nonfinite(self):
        self.assert_reject(b'{"type":"session.tool.called","x":NaN}\n')

    def test_reject_malformed_utf8(self):
        self.assert_reject(b'{"type":"session.tool.called","x":"\xff"}\n')

    def test_reject_malformed_json(self):
        self.assert_reject(b'{"type":"session.tool.called"\n')

    def test_reject_nonobject(self):
        self.assert_reject(b'["session.tool.called"]\n')

    def test_reject_invalid_properties(self):
        self.assert_reject(b'{"type":"session.tool.called","properties":null}\n')

    def test_reject_empty_record_or_stream(self):
        self.assert_reject(b"")
        self.assert_reject(b"\n")

    def test_reject_oversize_record(self):
        self.assert_reject(b"x" * (MAX_EVENT_BYTES + 1) + b"\n")


    def test_reject_stream_budget(self):
        line = json.dumps(event("session.tool.called", padding="x" * 200_000)).encode() + b"\n"
        count = (MAX_STREAM_BYTES // len(line)) + 1
        self.assert_reject(line * count)

    def test_reject_event_count_budget(self):
        line = b'{"type":"filesystem.changed"}\n'
        self.assert_reject(line * (MAX_EVENTS + 1))

    def test_reject_deeply_nested_json(self):
        raw = b'{"type":"session.tool.called","properties":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}\n'
        self.assert_reject(raw)

    def test_no_output_on_corruption_after_valid_events(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "events.jsonl"
            path.write_bytes(events(event("session.execution.succeeded")).getvalue() + b'{"type":')
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(["--input", str(path)])
            self.assertEqual(rc, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue().strip(), "INVALID_EVENT_STREAM")

    def test_sha_determinism_and_nonsecret_counts(self):
        one = events(event("session.step.started"), event("session.step.ended")).getvalue()
        p1 = project_events(io.BytesIO(one))
        p2 = project_events(io.BytesIO(one))
        self.assertEqual(p1, p2)
        self.assertTrue(p1["input_sha256"].startswith("sha256:"))

    def test_cli_success_does_not_echo_payload(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "events.jsonl"
            path.write_bytes(events(event("session.tool.called", token=SECRET)).getvalue())
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(["--input", str(path)])
            self.assertEqual(rc, 0)
            self.assertEqual(err.getvalue(), "")
            self.assertNotIn(SECRET, out.getvalue())
            self.assertEqual(json.loads(out.getvalue())["known_event_counts"]["session.tool.called"], 1)

    def test_cli_error_never_echoes_input_path(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / SECRET
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(["--input", str(path)])
            self.assertEqual(rc, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue().strip(), "INPUT_UNAVAILABLE")
            self.assertNotIn(SECRET, err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
