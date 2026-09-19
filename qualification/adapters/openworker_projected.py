#!/usr/bin/env python3
"""Minimal projected OpenWorker adapter for Model Spelunker qualification.

This adapter intentionally exposes only read_file/write_file to the model and leaves
task correctness to the external Model Spelunker verifier.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from typing import Any, Optional

import aisuite as ai

from coworker.engine import ApprovalOutcome, PermissionRequest, TurnEngine
from coworker.permissions import PermissionEngine
from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
from coworker.providers.router import ProviderRouter
from coworker.tools import ToolRegistry


MODEL = os.environ.get("MODEL_SPELUNKER_MODEL", "ollama:qwen3:1.7b")
MODEL_SETTINGS = {
    "parallel_tool_calls": False,
    "max_tokens": 2048,
    "reasoning_effort": "none",
}


class CapabilityEnforcingProvider(ProviderClient):
    """Keep one proposed tool call when the declared model is non-parallel."""

    def __init__(self, delegate: ProviderClient) -> None:
        self.delegate = delegate
        self.suppressed_batches: list[dict[str, Any]] = []

    def capabilities(self, model: str) -> ModelCapabilities:
        return self.delegate.capabilities(model)

    def _enforce(self, model: str, turn: AssistantTurn) -> AssistantTurn:
        calls = list(turn.tool_calls or [])
        if self.capabilities(model).parallel_tool_calls or len(calls) <= 1:
            return turn
        kept = calls[0]
        suppressed = calls[1:]
        self.suppressed_batches.append(
            {
                "kept": {"name": kept.name, "arguments": kept.arguments},
                "suppressed": [
                    {"name": call.name, "arguments": call.arguments}
                    for call in suppressed
                ],
            }
        )
        return replace(turn, tool_calls=[kept])

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        turn = self.delegate.complete(
            model=model,
            messages=messages,
            tools=tools,
            **settings,
        )
        return self._enforce(model, turn)

    def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ):
        for chunk in self.delegate.stream(
            model=model,
            messages=messages,
            tools=tools,
            **settings,
        ):
            if chunk.turn is None:
                yield chunk
            else:
                yield replace(chunk, turn=self._enforce(model, chunk.turn))


def registry_for(workspace: Path) -> ToolRegistry:
    available = {
        getattr(func, "__name__", ""): func
        for func in ai.toolkits.files(root=str(workspace), allow_write=True)
    }
    required = ("read_file", "write_file")
    missing = [name for name in required if name not in available]
    if missing:
        raise RuntimeError(f"OpenWorker file toolkit missing required tools: {missing}")

    registry = ToolRegistry()
    for name in required:
        registry.register(available[name])
    if registry.names() != list(required):
        raise RuntimeError(f"projected registry drift: {registry.names()}")
    return registry


def tool_names(messages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = function.get("name")
            if name:
                names.append(str(name))
    return names


async def run(instruction: str) -> int:
    workspace = Path.cwd().resolve()
    target = (workspace / "value.txt").resolve()
    registry = registry_for(workspace)
    permissions = PermissionEngine(workspace_root=workspace)
    provider = CapabilityEnforcingProvider(
        ProviderRouter(secrets=None, default_provider="openai")
    )

    approvals: list[dict[str, Any]] = []

    async def approver(request: PermissionRequest) -> ApprovalOutcome:
        arguments = dict(request.arguments or {})
        raw = str(arguments.get("path") or "")
        path = Path(raw)
        if not path.is_absolute():
            path = workspace / path
        allowed = (
            request.tool_name == "write_file"
            and path.resolve() == target
        )
        approvals.append(
            {
                "tool_name": request.tool_name,
                "path": raw,
                "allowed": allowed,
            }
        )
        return ApprovalOutcome.ONCE if allowed else ApprovalOutcome.DENY

    engine = TurnEngine(
        provider=provider,
        registry=registry,
        permissions=permissions,
        model=MODEL,
        approver=approver,
        max_iterations=4,
        model_settings=MODEL_SETTINGS,
    )

    counts: Counter[str] = Counter()
    async for event in engine.run(instruction):
        event_type = str(event.type)
        counts[event_type] += 1
        if event_type not in {
            "EventType.REASONING_DELTA",
            "EventType.ASSISTANT_DELTA",
        }:
            payload = dict(event.data or {})
            compact = {"type": event_type}
            for key in ("tool_calls", "status", "error", "error_type", "iterations"):
                if key in payload:
                    compact[key] = payload[key]
            print("OPENWORKER_EVENT=" + json.dumps(compact, sort_keys=True), flush=True)

    summary = {
        "model": MODEL,
        "model_settings": MODEL_SETTINGS,
        "projection": registry.names(),
        "tool_calls": tool_names(engine.messages),
        "approval_count": len(approvals),
        "approvals": approvals,
        "suppressed_speculative_batches": provider.suppressed_batches,
        "event_counts": dict(counts),
        "target_exists": target.is_file(),
    }
    print("OPENWORKER_SUMMARY=" + json.dumps(summary, sort_keys=True), flush=True)
    return 0


def main() -> int:
    instruction = sys.stdin.read().strip()
    if not instruction:
        print("missing task instruction on stdin", file=sys.stderr)
        return 2

    forbidden = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OLLAMA_API_KEY",
    )
    present = [name for name in forbidden if os.environ.get(name)]
    if present:
        print(
            "credential-free crossover received model credentials: " + ", ".join(present),
            file=sys.stderr,
        )
        return 2

    try:
        return asyncio.run(run(instruction))
    except Exception as exc:
        print(f"OPENWORKER_ERROR={type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
