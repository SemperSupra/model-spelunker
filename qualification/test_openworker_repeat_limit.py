#!/usr/bin/env python3
"""Focused repeat-policy tests using the existing optional protocol stubs.

Run this in a separate process from the admitted native-engine fixture: the
existing stub bootstrap intentionally populates sys.modules without that SDK.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from qualification import test_openworker_unprojected_tool_guard as protocol
from tool_repeat_limit import ENVIRONMENT_KEY, ToolRepeatLimit, ToolRepeatLimitError


ow = protocol.ow
TOOLS = [{"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
         for name in ("read_file", "write_file")]
CANARY = "PRIVATE_REPEAT_ARGUMENT_CANARY_348c"


def call(name="write_file", arguments=None):
    return SimpleNamespace(id="synthetic-call", name=name,
                           arguments={"path": "value.txt", "content": CANARY}
                           if arguments is None else arguments)


def turn(*calls, text=None):
    return protocol.AssistantTurn(text=text, tool_calls=list(calls), finish_reason="tool_calls")


@dataclass
class Chunk:
    text_delta: str | None = None
    reasoning_delta: str | None = None
    turn: object = None


class Delegate(protocol.ProviderClient):
    def __init__(self, responses, *, parallel=False):
        self.responses = list(responses)
        self.parallel = parallel
        self.requests = []

    def capabilities(self, model):
        return protocol.ModelCapabilities(parallel_tool_calls=self.parallel)

    def complete(self, **kwargs):
        self.requests.append(("complete", kwargs))
        return self.responses.pop(0)

    def stream(self, **kwargs):
        self.requests.append(("stream", kwargs))
        response = self.responses.pop(0)
        if isinstance(response, list):
            yield from response
        else:
            yield Chunk(turn=response)


class RepeatLimitTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))

    def provider(self, responses, *, limit=2, parallel=False):
        delegate = Delegate(responses, parallel=parallel)
        guard = ToolRepeatLimit(limit, {"read_file", "write_file"})
        return ow.CapabilityEnforcingProvider(delegate, repeat_limit=guard), delegate, guard

    @staticmethod
    def invoke(provider, mode):
        kwargs = {"model": "synthetic:repeat", "messages": [], "tools": TOOLS}
        if mode == "complete":
            return provider.complete(**kwargs)
        return list(provider.stream(**kwargs))

    def events(self):
        return [json.loads(line.split("=", 1)[1]) for line in self.output.getvalue().splitlines()
                if line.startswith("OPENWORKER_EVENT=")]

    def test_opt_in_configuration_and_disabled_no_inspection(self):
        self.assertEqual(ToolRepeatLimit.from_environment([], {}).limit, 0)
        self.assertEqual(ToolRepeatLimit.from_environment([], {ENVIRONMENT_KEY: "2"}).limit, 2)
        for value in ("", "-1", "25", "2.0", " 2", CANARY):
            with self.subTest(value=value), self.assertRaises(ValueError) as raised:
                ToolRepeatLimit.from_environment([], {ENVIRONMENT_KEY: value})
            self.assertNotIn(CANARY, str(raised.exception))

        class Uninspectable:
            def __iter__(self):
                raise AssertionError("disabled policy inspected calls")

        ToolRepeatLimit(0, []).check(Uninspectable(), call_index=1)
        response = turn(call(arguments=[CANARY]))
        for explicit_zero in (False, True):
            provider = ow.CapabilityEnforcingProvider(
                Delegate([response]),
                repeat_limit=ToolRepeatLimit(0, {"write_file"}) if explicit_zero else None,
            )
            self.assertIs(self.invoke(provider, "complete"), response)
            self.assertEqual(provider.model_calls_started, 1)
            self.assertEqual(len(provider.provider_observations), 1)
        self.assertEqual(self.events(), [])

    def test_canonical_objects_and_interleaving_do_not_reset_attempts(self):
        guard = ToolRepeatLimit(2, {"read_file", "write_file"})
        original = {"path": "value.txt", "options": {"b": 2, "a": [1, True, None]},
                    "content": CANARY}
        reordered = {"content": CANARY, "options": {"a": [1, True, None], "b": 2},
                     "path": "value.txt"}
        for index, proposed in enumerate((call(arguments=original),
                                           call("read_file", {"path": "other.txt"}),
                                           call(arguments={"path": "value.txt", "content": "different"}),
                                           call(arguments=reordered)), 1):
            guard.check([proposed], call_index=index)
        with self.assertRaisesRegex(ToolRepeatLimitError, "^REPEAT_LIMIT_EXCEEDED$"):
            guard.check([call(arguments=original)], call_index=5)
        self.assertEqual(guard.rejection, {"error_type": "REPEAT_LIMIT_EXCEEDED", "call_index": 5})
        self.assertNotIn(CANARY, json.dumps(guard.rejection))

    def test_non_json_arguments_fail_closed_but_unknown_tools_keep_denial(self):
        cycle = {}; cycle["self"] = cycle
        bad = [None, [], "{}", {"tuple": (1,)}, {1: "non-string-key"},
               {"value": float("nan")}, {"value": float("inf")},
               {"value": {CANARY}}, cycle]
        for arguments in bad:
            with self.subTest(kind=type(arguments).__name__):
                guard = ToolRepeatLimit(2, {"write_file"})
                # The unknown tool and its arguments remain the native engine's concern.
                guard.check([SimpleNamespace(name="unprojected", arguments=arguments)], call_index=1)
                with self.assertRaisesRegex(ToolRepeatLimitError, "^REPEAT_LIMIT_INVALID_ARGUMENTS$"):
                    guard.check([SimpleNamespace(name="write_file", arguments=arguments)], call_index=2)
                self.assertEqual(guard.rejection["call_index"], 2)
                self.assertNotIn(CANARY, json.dumps(guard.rejection))

    def test_whole_effective_batch_is_atomic(self):
        guard = ToolRepeatLimit(2, {"read_file", "write_file"})
        guard.check([call(), call()], call_index=1)
        before = guard._counts.copy()
        with self.assertRaises(ToolRepeatLimitError):
            guard.check([call("read_file", {"path": "new.txt"}), call()], call_index=2)
        self.assertEqual(guard._counts, before, "rejected batch partially committed counts")

        provider, delegate, guard = self.provider([turn(call(), call(), call())], parallel=True)
        with self.assertRaises(ToolRepeatLimitError):
            self.invoke(provider, "complete")
        self.assertEqual(guard._counts, {})
        self.assertEqual(len(delegate.requests), 1)
        self.assertEqual(len(provider.provider_observations), 1)
        self.assertEqual(provider.suppressed_batches, [])

    def test_sync_and_stream_rejections_latch_before_future_starts(self):
        for terminal_mode in ("complete", "stream"):
            with self.subTest(terminal_mode=terminal_mode):
                self.output.seek(0); self.output.truncate(0)
                last = (turn(call()) if terminal_mode == "complete" else
                        [Chunk(text_delta="visible fragment"), Chunk(turn=turn(call()))])
                provider, delegate, guard = self.provider([turn(call()), turn(call()), last])
                self.invoke(provider, "complete")
                self.invoke(provider, "stream")
                with self.assertRaisesRegex(ToolRepeatLimitError, "^REPEAT_LIMIT_EXCEEDED$"):
                    self.invoke(provider, terminal_mode)
                first = guard.rejection.copy()
                for mode in ("complete", "stream"):
                    with self.assertRaises(ToolRepeatLimitError):
                        self.invoke(provider, mode)
                self.assertEqual(guard.rejection, first)
                self.assertEqual(provider.model_calls_started, 3)
                self.assertEqual(len(delegate.requests), 3)
                self.assertEqual(len(provider.provider_observations), 3)
                self.assertEqual(self.events(), [{"type": "EventType.ERROR",
                    "error_type": "REPEAT_LIMIT_EXCEEDED", "call_index": 3}])
                self.assertNotIn(CANARY, self.output.getvalue())

    def test_normalization_precedes_count_and_salvaged_calls_are_counted(self):
        provider, _, _ = self.provider([turn(call(), call()) for _ in range(3)])
        for mode in ("complete", "stream"):
            result = self.invoke(provider, mode)
            finalized = result if mode == "complete" else result[-1].turn
            self.assertEqual(len(finalized.tool_calls), 1)
        with self.assertRaises(ToolRepeatLimitError):
            self.invoke(provider, "complete")
        self.assertEqual(len(provider.suppressed_batches), 3)

        text = "<tool_call><function=read_file></function></tool_call>"
        provider, _, _ = self.provider([turn(text=text) for _ in range(3)])
        self.invoke(provider, "complete")
        self.invoke(provider, "stream")
        with self.assertRaises(ToolRepeatLimitError):
            self.invoke(provider, "stream")

    def test_invalid_response_uses_bounded_terminal_channel(self):
        provider, _, guard = self.provider([turn(call(arguments={"value": {CANARY}}))])
        with self.assertRaisesRegex(ToolRepeatLimitError, "^REPEAT_LIMIT_INVALID_ARGUMENTS$"):
            self.invoke(provider, "stream")
        self.assertEqual(provider.model_calls_started, 1)
        self.assertEqual(provider.provider_observations, [])
        first = guard.rejection.copy()
        with self.assertRaises(ToolRepeatLimitError):
            self.invoke(provider, "complete")
        self.assertEqual(guard.rejection, first)
        self.assertEqual(self.events(), [{"type": "EventType.ERROR",
            "error_type": "REPEAT_LIMIT_INVALID_ARGUMENTS", "call_index": 1}])
        self.assertNotIn(CANARY, self.output.getvalue())

    def test_outer_exit_vetoes_valid_output_even_if_engine_catches_error(self):
        for swallow in (True, False):
            with self.subTest(engine_swallows=swallow), tempfile.TemporaryDirectory() as tmp:
                self.output.seek(0); self.output.truncate(0)
                delegate = Delegate([turn(call()) for _ in range(3)])
                target = Path(tmp) / "value.txt"

                class Engine:
                    def __init__(self, **kwargs):
                        self.provider = kwargs["provider"]
                        self.messages = []

                    async def run(self, instruction):
                        try:
                            for _ in range(3):
                                self.provider.complete(model="synthetic:repeat", messages=[], tools=TOOLS)
                                # This isolates the adapter's exit decision, not native dispatch.
                                target.write_text("READY\n")
                        except ToolRepeatLimitError as exc:
                            if not swallow:
                                raise
                            yield SimpleNamespace(type="EventType.ERROR", data={
                                "error_type": type(exc).__name__, "error": str(exc)})

                registry = mock.Mock()
                registry.names.return_value = ["read_file", "write_file"]
                env = {ENVIRONMENT_KEY: "2", "MODEL_SPELUNKER_ALLOWED_WRITE_PATHS": "value.txt"}
                original = Path.cwd()
                try:
                    os.chdir(tmp)
                    with mock.patch.dict(os.environ, env, clear=True), \
                         mock.patch.object(ow, "MODEL", "synthetic:repeat"), \
                         mock.patch.object(ow, "_PROVIDER", "synthetic"), \
                         mock.patch.object(ow, "ProviderRouter", return_value=delegate), \
                         mock.patch.object(ow, "registry_for", return_value=registry), \
                         mock.patch.object(ow, "PermissionEngine"), \
                         mock.patch.object(ow, "Mode", SimpleNamespace(CUSTOM="custom")), \
                         mock.patch.object(ow, "TurnEngine", Engine), \
                         mock.patch.object(ow, "mobile_action_log", return_value=[]), \
                         mock.patch.object(sys, "stdin", io.StringIO("Write the fixture.")), \
                         contextlib.redirect_stderr(io.StringIO()):
                        code = ow.main()
                finally:
                    os.chdir(original)
                self.assertEqual(code, 1)
                self.assertEqual(target.read_text(), "READY\n")
                self.assertEqual(len(delegate.requests), 3)
                self.assertEqual(self.events(), [{"type": "EventType.ERROR",
                    "error_type": "REPEAT_LIMIT_EXCEEDED", "call_index": 3}])


if __name__ == "__main__":
    unittest.main()
