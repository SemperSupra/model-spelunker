#!/usr/bin/env python3
"""Exercise the real pinned OpenWorker loop with a synthetic provider, no model.

Run separately after installing the admitted OpenWorker artifact:
    python qualification/tests/test_completion_guard_native.py --require-native

No fallback/copy of TurnEngine is permitted. Optional local runs skip only when
OpenWorker is absent; the CI command must require it and verify its source blob.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qualification" / "adapters"))
REQUIRE_NATIVE = "--require-native" in sys.argv
if REQUIRE_NATIVE:
    sys.argv.remove("--require-native")

NATIVE_AVAILABLE = importlib.util.find_spec("coworker") is not None
if REQUIRE_NATIVE and not NATIVE_AVAILABLE:
    raise SystemExit("Native completion-guard test requires the admitted OpenWorker artifact")
if NATIVE_AVAILABLE:
    from coworker.engine import TurnEngine as RealTurnEngine
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient, ToolCall
    import openworker_projected as ow

EXPECTED_SOURCE = "5bc10d928e0b64aae74313349a3b17bd19643ae2"
EXPECTED_ENGINE_BLOB = "e492443c42a646ddfd86b36e9732b1e6c76042bf"


class ScriptedProvider(ProviderClient if NATIVE_AVAILABLE else object):
    """Only provider responses are scripted; engine and file tools are native."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def capabilities(self, model):
        return ModelCapabilities(parallel_tool_calls=False)

    def complete(self, *, model, messages, tools=None, **settings):
        self.requests.append(copy.deepcopy(messages))
        if not self.responses:
            raise AssertionError("engine exceeded the declared scripted call budget")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response() if callable(response) else response


@unittest.skipUnless(NATIVE_AVAILABLE, "admitted OpenWorker artifact not installed")
class NativeCompletionGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(inspect.getsourcefile(RealTurnEngine)).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
        if blob != EXPECTED_ENGINE_BLOB:
            raise AssertionError(f"unqualified TurnEngine source: {blob}; expected {EXPECTED_ENGINE_BLOB}")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-completion-guard-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "evidence.txt").write_text("synthetic evidence; no gold answer")
        self.engines = []

    @staticmethod
    def stopped(text="I have finished", reason="stop"):
        return AssistantTurn(text=text, finish_reason=reason)

    @staticmethod
    def tool(name, arguments, index):
        return AssistantTurn(
            tool_calls=[ToolCall(id=f"synthetic-{index}", name=name, arguments=arguments)],
            finish_reason="tool_calls",
        )

    def execute(self, responses, *, enabled=True, limit=4):
        delegate = ScriptedProvider(responses)
        env = {
            "MODEL_SPELUNKER_COMPLETION_CHECK": "required-files-v1" if enabled else "none",
            "MODEL_SPELUNKER_REQUIRED_OUTPUT_PATHS": '["result.json"]',
            "MODEL_SPELUNKER_ALLOWED_WRITE_PATHS": "result.json",
            "MODEL_SPELUNKER_PROJECTED_TOOLS": "read_file,write_file",
            "MODEL_SPELUNKER_TOOL_HINT_MODE": "none",
            "MODEL_SPELUNKER_TASK_ID": "synthetic-guard-contract",
        }

        def engine_factory(**kwargs):
            engine = RealTurnEngine(**kwargs)
            engine.run = mock.Mock(wraps=engine.run)
            engine.queue_steering = mock.Mock(wraps=engine.queue_steering)
            engine.permissions.clear_run_allowances = mock.Mock(
                wraps=engine.permissions.clear_run_allowances
            )
            self.engines.append(engine)
            return engine

        output = io.StringIO()
        old_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            with mock.patch.dict(os.environ, env), \
                 mock.patch.object(ow, "MODEL", "synthetic:completion-guard"), \
                 mock.patch.object(ow, "_PROVIDER", "synthetic"), \
                 mock.patch.object(ow, "MAX_ITERATIONS", limit), \
                 mock.patch.object(ow, "MODEL_SETTINGS", {"max_tokens": 256}), \
                 mock.patch.object(ow, "ProviderRouter", return_value=delegate), \
                 mock.patch.object(ow, "TurnEngine", side_effect=engine_factory), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(asyncio.run(ow.run("Create the required result.json from evidence.")), 0)
        finally:
            os.chdir(old_cwd)
        summaries = [json.loads(line.split("=", 1)[1]) for line in output.getvalue().splitlines()
                     if line.startswith("OPENWORKER_SUMMARY=")]
        self.assertEqual(len(summaries), 1)
        engine = self.engines[-1]
        engine.run.assert_called_once()
        self.assertEqual(engine.max_iterations, limit)
        self.assertLessEqual(len(delegate.requests), limit)
        # Only the initial and final run boundaries clear grants. Steering must
        # not enter another run and reset any turn-scoped permission handling.
        self.assertEqual(engine.permissions.clear_run_allowances.call_count, 2)
        return delegate, engine, summaries[0]

    def test_real_adapter_continues_same_transcript_without_oracle(self):
        wrong = '{"deliberately_wrong":true}'
        delegate, engine, summary = self.execute([
            self.stopped("No artifact has been written yet."),
            self.tool("write_file", {"path": "result.json", "content": wrong}, 2),
            self.stopped(),
        ])
        self.assertEqual(len(delegate.requests), 3)
        engine.queue_steering.assert_called_once()
        self.assertEqual(summary["completion_guard"]["nudges"], 1)
        self.assertEqual((self.root / "result.json").read_text(), wrong)
        self.assertEqual(delegate.requests[0], delegate.requests[1][:1])
        self.assertEqual([m["role"] for m in delegate.requests[1]], ["user", "assistant", "user"])
        self.assertIn("Harness completion check", delegate.requests[1][-1]["content"])
        self.assertNotIn("deliberately_wrong", delegate.requests[1][-1]["content"])
        self.assertEqual(summary["event_counts"]["EventType.TURN_START"], 1)

    def test_real_loop_keeps_total_four_call_cap(self):
        delegate, engine, summary = self.execute([
            self.stopped(),
            self.tool("read_file", {"path": "evidence.txt"}, 2),
            self.tool("read_file", {"path": "evidence.txt"}, 3),
            self.tool("read_file", {"path": "evidence.txt"}, 4),
            self.stopped("This fifth response must never be requested."),
        ])
        self.assertEqual(len(delegate.requests), 4)
        self.assertEqual(len(delegate.responses), 1)
        self.assertEqual(summary["completion_guard"]["nudges"], 1)
        self.assertFalse((self.root / "result.json").exists())
        self.assertEqual(summary["event_counts"]["EventType.TURN_END"], 1)

    def test_second_stop_cannot_create_a_second_nudge(self):
        delegate, engine, summary = self.execute([self.stopped(), self.stopped()])
        self.assertEqual(len(delegate.requests), 2)
        self.assertEqual(summary["completion_guard"]["nudges"], 1)
        engine.queue_steering.assert_called_once()

    def test_disabled_and_existing_incorrect_output_do_not_continue(self):
        delegate, engine, summary = self.execute([self.stopped()], enabled=False)
        self.assertEqual(len(delegate.requests), 1)
        engine.queue_steering.assert_not_called()
        (self.root / "result.json").write_text("wrong contents")
        delegate, engine, summary = self.execute([self.stopped()])
        self.assertEqual(len(delegate.requests), 1)
        engine.queue_steering.assert_not_called()
        self.assertEqual(summary["completion_guard"]["nudges"], 0)

    def test_real_error_denial_length_and_salvaged_protocol_do_not_continue(self):
        cases = [
            ("provider-error", [RuntimeError("synthetic transport failure")]),
            ("length", [self.stopped(reason="length")]),
            ("denied-write", [
                self.tool("write_file", {"path": "forbidden.txt", "content": "not allowed"}, 1),
                self.stopped(),
            ]),
            ("stray-tool-markup", [self.stopped("Done.</tool_call>")]),
        ]
        for name, responses in cases:
            with self.subTest(name=name):
                delegate, engine, summary = self.execute(responses)
                engine.queue_steering.assert_not_called()
                self.assertEqual(summary["completion_guard"]["nudges"], 0)
                self.assertFalse((self.root / "forbidden.txt").exists())

    def test_actual_interruption_cannot_trigger_feedback(self):
        def interrupted_response():
            self.engines[-1].request_interrupt()
            return self.stopped()
        delegate, engine, summary = self.execute([interrupted_response])
        self.assertEqual(len(delegate.requests), 1)
        engine.queue_steering.assert_not_called()
        self.assertEqual(summary["completion_guard"]["nudges"], 0)
        self.assertGreaterEqual(summary["event_counts"].get("EventType.INTERRUPTED", 0), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
