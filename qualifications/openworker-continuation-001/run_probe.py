#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from coworker.engine import TurnEngine
from coworker.events import EventType
from coworker.permissions import Mode, PermissionEngine
from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient, ToolCall
from coworker.tools.registry import ToolRegistry

PLAN_PATH = Path(os.environ.get("CONTINUATION_PLAN", "plan.json"))
RESULT_PATH = Path(os.environ.get("RESULT_JSON", "result.json"))


class ScriptedProvider(ProviderClient):
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.turns = list(turns)
        self.calls = 0
        self.messages_seen: list[list[dict[str, Any]]] = []

    def complete(self, *, model: str, messages: list[dict[str, Any]], tools=None, **settings: Any) -> AssistantTurn:
        self.messages_seen.append(messages)
        if self.calls >= len(self.turns):
            raise RuntimeError("scripted provider exhausted")
        turn = self.turns[self.calls]
        self.calls += 1
        return turn

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(tools=True, streaming=False)


def schema(name: str, description: str, properties: dict[str, Any] | None = None,
           required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


def tool_turn(call_id: str, name: str, arguments: dict[str, Any] | None = None) -> AssistantTurn:
    return AssistantTurn(
        text=None,
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments or {})],
        finish_reason="tool_calls",
    )


def prose_turn(text: str, finish_reason: str = "stop") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[], finish_reason=finish_reason)


async def execute_case(case_id: str, *, enable_guard: bool, prose_finish_reason: str,
                       first_test_passes: bool) -> dict[str, Any]:
    validator = {"passed": False, "calls": 0}
    writes = {"count": 0}

    first_result = "PASS" if first_test_passes else "FAIL"
    turns = [
        tool_turn("tc1", "run_tests"),
        prose_turn(
            "The test still has issues. Let me rewrite it carefully before testing again."
            if not first_test_passes
            else "Verification passed; the task is complete.",
            finish_reason=prose_finish_reason,
        ),
    ]
    if not first_test_passes:
        turns.extend([
            tool_turn("tc2", "write_solution", {"text": "fixed"}),
            tool_turn("tc3", "run_tests"),
            prose_turn("Verified. The repaired solution passes.", finish_reason="stop"),
        ])

    provider = ScriptedProvider(turns)

    with tempfile.TemporaryDirectory(prefix="openworker-continuation-") as td:
        root = Path(td)
        registry = ToolRegistry()

        def run_tests() -> str:
            validator["calls"] += 1
            if validator["calls"] == 1:
                validator["passed"] = first_test_passes
                return first_result
            validator["passed"] = True
            return "PASS"

        def write_solution(text: str) -> str:
            writes["count"] += 1
            (root / "solution.txt").write_text(text, encoding="utf-8")
            return "solution written"

        registry.register(
            run_tests,
            schema=schema("run_tests", "Run the objective verifier and return PASS or FAIL."),
        )
        registry.register(
            write_solution,
            schema=schema(
                "write_solution",
                "Write one repaired candidate.",
                {"text": {"type": "string"}},
                ["text"],
            ),
        )

        permissions = PermissionEngine(workspace_root=root, mode=Mode.BYPASS_APPROVALS)
        engine = TurnEngine(
            provider=provider,
            registry=registry,
            permissions=permissions,
            model="scripted-model",
            instructions="Use the verifier. Repair only if verification fails.",
            max_iterations=6,
        )

        events: list[dict[str, Any]] = []
        steering_count = 0
        async for event in engine.run("verify and repair if needed"):
            events.append({"type": event.type.value, "data": event.data})
            if (
                enable_guard
                and event.type == EventType.ASSISTANT_MESSAGE
                and not event.data.get("tool_calls")
                and not validator["passed"]
            ):
                engine.queue_steering(
                    "Objective verification is still failing. Continue the same task using the available tools; do not stop until verification passes or the iteration limit is reached."
                )
                steering_count += 1

        turn_end = next((e["data"] for e in reversed(events) if e["type"] == "turn_end"), {})
        return {
            "case_id": case_id,
            "provider_calls": provider.calls,
            "validator_passed": validator["passed"],
            "validator_calls": validator["calls"],
            "writes": writes["count"],
            "steering_count": steering_count,
            "turn_status": turn_end.get("status"),
            "turn_iterations": turn_end.get("iterations"),
            "events": events,
            "messages": engine.messages,
        }


async def main_async() -> int:
    plan_bytes = PLAN_PATH.read_bytes()
    cases = [
        await execute_case(
            "baseline-stop-prose",
            enable_guard=False,
            prose_finish_reason="stop",
            first_test_passes=False,
        ),
        await execute_case(
            "validator-steering-stop",
            enable_guard=True,
            prose_finish_reason="stop",
            first_test_passes=False,
        ),
        await execute_case(
            "validator-steering-length",
            enable_guard=True,
            prose_finish_reason="length",
            first_test_passes=False,
        ),
        await execute_case(
            "no-steering-after-pass",
            enable_guard=True,
            prose_finish_reason="stop",
            first_test_passes=True,
        ),
    ]

    expected = {
        "baseline-stop-prose": {"provider_calls": 2, "turn_status": "completed", "validator_passed": False, "steering_count": 0},
        "validator-steering-stop": {"provider_calls": 5, "turn_status": "completed", "validator_passed": True, "steering_count": 1},
        "validator-steering-length": {"provider_calls": 5, "turn_status": "completed", "validator_passed": True, "steering_count": 1},
        "no-steering-after-pass": {"provider_calls": 2, "turn_status": "completed", "validator_passed": True, "steering_count": 0},
    }

    failures = []
    for case in cases:
        exp = expected[case["case_id"]]
        for key, value in exp.items():
            if case.get(key) != value:
                failures.append({
                    "case_id": case["case_id"],
                    "field": key,
                    "expected": value,
                    "actual": case.get(key),
                })

    result = {
        "schema_version": 1,
        "record_type": "framework-continuation-result",
        "experiment_id": "openworker-validator-steering-001",
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "openworker_revision": os.environ.get("OPENWORKER_REVISION", ""),
        "execution_disposition": "completed",
        "scientific_disposition": "supported" if not failures else "not_supported",
        "failures": failures,
        "cases": cases,
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if not failures else 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
