#!/usr/bin/env python3
"""Passive-observer parity on the actual admitted engine, without a model.

Use --require-native in CI; absence may skip only optional local runs. Provider
responses and one tool exception are scripted. The engine, registry, file write,
permission handling, transcript, and iteration bound are native, never copied.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import hashlib
import importlib.util
import inspect
import io
import itertools
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qualification" / "adapters"))
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--require-native", action="store_true")
parser.add_argument("--receipt", type=Path)
OPTIONS, TEST_ARGS = parser.parse_known_args()
NATIVE_AVAILABLE = importlib.util.find_spec("coworker") is not None
if OPTIONS.require_native and not NATIVE_AVAILABLE:
    raise SystemExit("Native observation test requires the admitted OpenWorker artifact")
if NATIVE_AVAILABLE:
    import coworker.engine as native_engine
    from coworker.engine import TurnEngine as RealTurnEngine
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient, ToolCall
    import openworker_projected as ow

EXPECTED_SOURCE = "5bc10d928e0b64aae74313349a3b17bd19643ae2"
EXPECTED_ENGINE_BLOB = "e492443c42a646ddfd86b36e9732b1e6c76042bf"
CANARY = "PRIVATE_TOOL_OBSERVATION_CANARY_739a"


class ScriptedProvider(ProviderClient if NATIVE_AVAILABLE else object):
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def capabilities(self, model):
        return ModelCapabilities(parallel_tool_calls=False)

    def complete(self, *, model, messages, tools=None, **settings):
        self.requests.append(copy.deepcopy({"model": model, "messages": messages,
                                            "tools": tools, "settings": settings}))
        if not self.responses:
            raise AssertionError("engine exceeded scripted model-call budget")
        return self.responses.pop(0)


class NoObservation:
    """Baseline removes both observation hooks, including the native audit sink."""
    audit = None

    def __init__(self, projected_names):
        pass

    def observe_event(self, event_type, payload):
        pass

    def snapshot(self):
        return {}


@unittest.skipUnless(NATIVE_AVAILABLE, "admitted OpenWorker artifact not installed")
class NativeToolObservationTests(unittest.TestCase):
    observations = {}

    @classmethod
    def setUpClass(cls):
        source = Path(inspect.getsourcefile(RealTurnEngine)).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
        if blob != EXPECTED_ENGINE_BLOB:
            raise AssertionError(f"unqualified native engine blob: {blob}")

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="native-tool-observation-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.target = self.root / f"{CANARY}.txt"
        self.forbidden = self.root / f"forbidden-{CANARY}.txt"

    @staticmethod
    def tool(name, arguments, index):
        return AssistantTurn(tool_calls=[ToolCall(id=f"scripted-{index}", name=name,
                                                 arguments=arguments)],
                             finish_reason="tool_calls")

    @staticmethod
    def stopped():
        return AssistantTurn(text="Synthetic fixture complete.", finish_reason="stop")

    def execute(self, responses, *, enabled, limit=4, raise_read=False):
        self.target.unlink(missing_ok=True)
        delegate = ScriptedProvider(copy.deepcopy(responses))
        engines = []
        real_registry_for = ow.registry_for
        # Exact e492443... engine uses time.time() only at its six message-append
        # sites. Give each arm identical increasing timestamps while preserving
        # full raw-history equality. Replace this module binding, never Python's
        # shared time.time or the provider/asyncio duration clocks.
        message_clock = SimpleNamespace(time=mock.Mock(side_effect=itertools.count(1700000000.0)))

        def registry_factory(workspace):
            registry = real_registry_for(workspace)
            if raise_read:
                def scripted_read(**arguments):
                    raise FileNotFoundError(CANARY)
                # Retain the admitted tool's native schema and permission metadata.
                registry.get("read_file").func = scripted_read
            return registry

        def engine_factory(**kwargs):
            engine = RealTurnEngine(**kwargs)
            engine.run = mock.Mock(wraps=engine.run)
            engine.permissions.clear_run_allowances = mock.Mock(
                wraps=engine.permissions.clear_run_allowances)
            engines.append(engine)
            return engine

        env = {"MODEL_SPELUNKER_ALLOWED_WRITE_PATHS": self.target.name,
               "MODEL_SPELUNKER_PROJECTED_TOOLS": "read_file,write_file",
               "MODEL_SPELUNKER_TASK_ID": "synthetic-observation-contract",
               "MODEL_SPELUNKER_TOOL_HINT_MODE": "none"}
        output = io.StringIO()
        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            with mock.patch.dict(os.environ, env), \
                 mock.patch.object(ow, "MODEL", "synthetic:tool-observations"), \
                 mock.patch.object(ow, "_PROVIDER", "synthetic"), \
                 mock.patch.object(ow, "MODEL_SETTINGS", {"max_tokens": 256}), \
                 mock.patch.object(ow, "MAX_ITERATIONS", limit), \
                 mock.patch.object(ow, "ProviderRouter", return_value=delegate), \
                 mock.patch.object(ow, "registry_for", side_effect=registry_factory), \
                 mock.patch.object(ow, "TurnEngine", side_effect=engine_factory), \
                 mock.patch.object(native_engine, "time", message_clock), \
                 mock.patch.object(ow, "ToolResultObserver",
                                   ow.ToolResultObserver if enabled else NoObservation), \
                 contextlib.redirect_stdout(output):
                exit_code = asyncio.run(ow.run("Complete the synthetic fixture."))
        finally:
            os.chdir(original_cwd)
        summaries = [json.loads(line.split("=", 1)[1]) for line in output.getvalue().splitlines()
                     if line.startswith("OPENWORKER_SUMMARY=")]
        self.assertEqual(len(summaries), 1)
        engine = engines[0]
        engine.run.assert_called_once()
        self.assertEqual(engine.max_iterations, limit)
        self.assertLessEqual(len(delegate.requests), limit)
        self.assertEqual(engine.permissions.clear_run_allowances.call_count, 2)
        self.assertFalse(self.forbidden.exists(), "denied write executed")
        return {"requests": delegate.requests, "messages": copy.deepcopy(engine.messages),
                "summary": summaries[0], "exit_code": exit_code,
                "output": self.target.read_bytes() if self.target.exists() else None,
                "message_clock_calls": message_clock.time.call_count,
                "remaining_responses": len(delegate.responses)}

    def assert_parity(self, before, after):
        for key in ("requests", "messages", "message_clock_calls", "exit_code",
                    "output", "remaining_responses"):
            # Failure diagnostics must not print actor arguments, content, or paths.
            self.assertTrue(before[key] == after[key], f"observer changed {key}")
        for key in ("tool_calls", "approvals", "approval_count", "event_counts",
                    "max_iterations", "projection", "target_exists", "model_settings",
                    "suppressed_speculative_batches", "unprojected_tool_calls"):
            self.assertTrue(before["summary"][key] == after["summary"][key],
                            f"observer changed {key}")
        self.assertEqual(after["exit_code"], 0)
        self.assertNotIn(CANARY, json.dumps(after["summary"]["tool_result_observations"]))

    def test_native_error_denial_success_preserve_actor_and_permission_behavior(self):
        responses = [self.tool("read_file", {"path": CANARY}, 1),
                     self.tool("write_file", {"path": self.forbidden.name, "content": CANARY}, 2),
                     self.tool("write_file", {"path": self.target.name, "content": CANARY}, 3),
                     self.stopped()]
        before = self.execute(responses, enabled=False, raise_read=True)
        after = self.execute(responses, enabled=True, raise_read=True)
        self.assert_parity(before, after)
        self.assertEqual(len(after["requests"]), 4)
        self.assertTrue(after["output"] == CANARY.encode(), "authorized write did not complete")
        observation = after["summary"]["tool_result_observations"]
        self.assertEqual(observation["event_count"], 3)
        self.assertEqual(observation["finished_audit_count"], 3)
        self.assertEqual(observation["results"], [
            {"index": 1, "tool": "read_file", "status": "error", "error_type": "FileNotFoundError"},
            {"index": 2, "tool": "write_file", "status": "denied", "error_type": "unknown"},
            {"index": 3, "tool": "write_file", "status": "ok", "error_type": "unknown"},
        ])
        self.observations["error-denial-success"] = observation

    def test_native_iteration_cap_and_repeated_tools_are_unchanged(self):
        responses = [self.tool("write_file", {"path": self.target.name, "content": CANARY}, i)
                     for i in (1, 2)] + [self.stopped()]
        before = self.execute(responses, enabled=False, limit=2)
        after = self.execute(responses, enabled=True, limit=2)
        self.assert_parity(before, after)
        self.assertEqual(len(after["requests"]), 2)
        self.assertEqual(after["remaining_responses"], 1)
        self.assertEqual(after["summary"]["tool_result_observations"]["event_count"], 2)
        self.observations["iteration-cap"] = after["summary"]["tool_result_observations"]

    def test_native_unknown_tool_has_explicit_missing_audit_and_no_guessed_class(self):
        responses = [self.tool("unprojected_tool", {"path": CANARY}, 1), self.stopped()]
        before = self.execute(responses, enabled=False)
        after = self.execute(responses, enabled=True)
        self.assert_parity(before, after)
        observation = after["summary"]["tool_result_observations"]
        self.assertEqual(observation["event_count"], 1)
        self.assertEqual(observation["finished_audit_count"], 0)
        self.assertEqual(observation["results"], [
            {"index": 1, "tool": "unknown", "status": "error", "error_type": "unknown"}])
        self.observations["missing-native-audit"] = observation

    def test_full_transcript_parity_rejects_mutations_after_last_provider_request(self):
        captured = self.execute([
            self.tool("write_file", {"path": self.target.name, "content": CANARY}, 1),
            self.stopped(),
        ], enabled=True, limit=1)
        self.assertEqual(len(captured["requests"]), 1)
        self.assertEqual(captured["remaining_responses"], 1)
        self.assert_parity(captured, copy.deepcopy(captured))
        tool_index = next(i for i, message in enumerate(captured["messages"])
                          if message.get("role") == "tool")
        tool_message = captured["messages"][tool_index]
        self.assertIn("approval_grant", tool_message["_display"])
        mutations = {
            "content": lambda m: m.__setitem__("content", "synthetic changed result"),
            "call-id": lambda m: m.__setitem__("tool_call_id", "mutated-call"),
            "sidecar": lambda m: m["_display"].__setitem__("approval_grant", "deny"),
            "timestamp": lambda m: m.__setitem__("ts", m["ts"] + 0.25),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                altered = copy.deepcopy(captured)
                mutate(altered["messages"][tool_index])
                # Requests stay identical: the terminal result was produced at
                # the iteration cap and has never been sent to the provider.
                with self.assertRaisesRegex(AssertionError, "observer changed messages"):
                    self.assert_parity(captured, altered)


if __name__ == "__main__":
    program = unittest.main(argv=[sys.argv[0], *TEST_ARGS], verbosity=2, exit=False)
    result = program.result
    passed = result.wasSuccessful() and NATIVE_AVAILABLE and not result.skipped
    if OPTIONS.receipt:
        OPTIONS.receipt.parent.mkdir(parents=True, exist_ok=True)
        OPTIONS.receipt.write_text(json.dumps({
            "record_type": "openworker-native-tool-observation-contract",
            "result": "PASS" if passed else "NOT_PASSED",
            "harness_source_revision": EXPECTED_SOURCE,
            "engine_git_blob": EXPECTED_ENGINE_BLOB,
            "native_required": OPTIONS.require_native,
            "message_clock": "fixture-scoped-increasing-append-timestamps",
            "tests_run": result.testsRun, "tests_skipped": len(result.skipped),
            "failures": len(result.failures), "errors": len(result.errors),
            "observations": NativeToolObservationTests.observations,
            "source_sha256": {
                relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                for relative in (
                    "qualification/adapters/openworker_projected.py",
                    "qualification/adapters/tool_result_observations.py",
                    "qualification/tests/test_tool_result_observations_native.py",
                )
            },
        }, sort_keys=True, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
