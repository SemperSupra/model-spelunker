#!/usr/bin/env python3
"""Minimal projected OpenWorker adapter for Model Spelunker qualification.

This adapter exposes only the task-declared file/mobile tools and leaves task
correctness to the external Model Spelunker verifier.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

import aisuite as ai

from coworker.engine import ApprovalOutcome, PermissionRequest, TurnEngine
from coworker.permissions import Mode, PermissionEngine
from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
from coworker.providers.router import ProviderRouter
from coworker.tools import ToolRegistry

from android_mobile_tools import mobile_action_log, mobile_tool_functions


MODEL = os.environ.get("MODEL_SPELUNKER_MODEL", "ollama:qwen3:1.7b")
_PROVIDER, _, _BARE_MODEL = MODEL.partition(":")
_reasoning_effort = os.environ.get("MODEL_SPELUNKER_REASONING_EFFORT", "none")
MODEL_SETTINGS = {
    "parallel_tool_calls": False,
    "max_tokens": int(os.environ.get("MODEL_SPELUNKER_MAX_TOKENS", "2048")),
}
MAX_ITERATIONS = int(os.environ.get("MODEL_SPELUNKER_MAX_ITERATIONS", "4"))
if not 1 <= MAX_ITERATIONS <= 24:
    raise RuntimeError("MODEL_SPELUNKER_MAX_ITERATIONS must be between 1 and 24")
if _reasoning_effort != "omit":
    MODEL_SETTINGS["reasoning_effort"] = _reasoning_effort

_extra_body_raw = os.environ.get("MODEL_SPELUNKER_EXTRA_BODY")
if _extra_body_raw:
    parsed_extra_body = json.loads(_extra_body_raw)
    if not isinstance(parsed_extra_body, dict):
        raise RuntimeError("MODEL_SPELUNKER_EXTRA_BODY must decode to an object")
    MODEL_SETTINGS["extra_body"] = parsed_extra_body


class CapabilityEnforcingProvider(ProviderClient):
    """Keep one proposed tool call when the declared model is non-parallel."""

    def __init__(self, delegate: ProviderClient) -> None:
        self.delegate = delegate
        self.suppressed_batches: list[dict[str, Any]] = []
        self.provider_observations: list[dict[str, Any]] = []
        self.model_calls_started = 0

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        dumper = getattr(value, "model_dump", None)
        if callable(dumper):
            try:
                dumped = dumper()
                return dumped if isinstance(dumped, dict) else {}
            except Exception:
                return {}
        return {}

    @staticmethod
    def _bytes(value: Any) -> int:
        return len(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )

    def _mark_model_call_started(
        self,
        *,
        requested_model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]],
    ) -> None:
        self.model_calls_started += 1
        marker = {
            "index": self.model_calls_started,
            "requested_model": requested_model,
            "request_message_bytes": self._bytes(messages),
            "request_tool_schema_bytes": self._bytes(tools or []),
        }
        print(
            "MODEL_SPELUNKER_MODEL_CALL_STARTED=" + json.dumps(marker, sort_keys=True),
            flush=True,
        )

    def _observe(
        self,
        *,
        requested_model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]],
        turn: AssistantTurn,
        started: float,
        first_event_at: float | None,
    ) -> None:
        raw = self._mapping(turn.raw)
        usage = self._mapping(raw.get("usage"))
        prompt_details = self._mapping(usage.get("prompt_tokens_details"))

        tool_argument_bytes = sum(
            self._bytes(call.arguments) for call in (turn.tool_calls or [])
        )
        observation = {
            "requested_model": requested_model,
            "resolved_model": raw.get("model"),
            "_response_id": raw.get("id"),
            "provider": raw.get("provider"),
            "system_fingerprint": raw.get("system_fingerprint"),
            "service_tier": raw.get("service_tier"),
            "finish_reason": turn.finish_reason,
            "request_message_bytes": self._bytes(messages),
            "request_tool_schema_bytes": self._bytes(tools or []),
            "output_text_bytes": len((turn.text or "").encode("utf-8")),
            "reasoning_bytes": len((turn.reasoning or "").encode("utf-8")),
            "tool_argument_bytes": tool_argument_bytes,
            "client_wall_seconds": round(time.monotonic() - started, 6),
            "first_event_seconds": (
                round(first_event_at - started, 6)
                if first_event_at is not None
                else None
            ),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "cached_tokens": prompt_details.get("cached_tokens"),
            "cache_write_tokens": prompt_details.get("cache_write_tokens"),
            "queue_time": usage.get("queue_time"),
            "prompt_time": usage.get("prompt_time"),
            "completion_time": usage.get("completion_time"),
            "provider_total_time": usage.get("total_time"),
            "provider_cost": usage.get("cost"),
        }
        self.provider_observations.append(
            {key: value for key, value in observation.items() if value is not None}
        )

    def enrich_openrouter_generations(self) -> None:
        if _PROVIDER != "openrouter":
            return
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            return
        allowed = (
            "model",
            "provider_name",
            "router",
            "service_tier",
            "streamed",
            "cancelled",
            "finish_reason",
            "native_finish_reason",
            "native_tokens_prompt",
            "native_tokens_completion",
            "native_tokens_reasoning",
            "native_tokens_cached",
            "tokens_prompt",
            "tokens_completion",
            "total_cost",
            "upstream_inference_cost",
            "latency",
            "generation_time",
            "moderation_latency",
            "data_region",
            "is_byok",
        )
        for observation in self.provider_observations:
            response_id = observation.get("_response_id")
            if not isinstance(response_id, str) or not response_id:
                continue
            url = (
                "https://openrouter.ai/api/v1/generation?"
                + urllib.parse.urlencode({"id": response_id})
            )
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": "Bearer " + key,
                },
                method="GET",
            )
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(request, timeout=20) as response:
                        payload = json.load(response)
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if isinstance(data, dict):
                        observation["openrouter_generation"] = {
                            name: data.get(name)
                            for name in allowed
                            if data.get(name) is not None
                        }
                    break
                except urllib.error.HTTPError as exc:
                    retryable = exc.code in {404, 429, 500, 502}
                    if retryable and attempt < 3:
                        time.sleep(0.25 * (2 ** attempt))
                        continue
                    observation["openrouter_generation_error"] = f"HTTPError:{exc.code}"
                    break
                except Exception as exc:
                    observation["openrouter_generation_error"] = type(exc).__name__
                    break

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
        started = time.monotonic()
        self._mark_model_call_started(
            requested_model=model,
            messages=messages,
            tools=tools,
        )
        turn = self.delegate.complete(
            model=model,
            messages=messages,
            tools=tools,
            **settings,
        )
        turn = self._enforce(model, turn)
        self._observe(
            requested_model=model,
            messages=messages,
            tools=tools,
            turn=turn,
            started=started,
            first_event_at=None,
        )
        return turn

    def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ):
        started = time.monotonic()
        first_event_at: float | None = None
        self._mark_model_call_started(
            requested_model=model,
            messages=messages,
            tools=tools,
        )
        for chunk in self.delegate.stream(
            model=model,
            messages=messages,
            tools=tools,
            **settings,
        ):
            if first_event_at is None and (
                chunk.text_delta is not None
                or chunk.reasoning_delta is not None
                or chunk.turn is not None
            ):
                first_event_at = time.monotonic()
            if chunk.turn is None:
                yield chunk
            else:
                turn = self._enforce(model, chunk.turn)
                self._observe(
                    requested_model=model,
                    messages=messages,
                    tools=tools,
                    turn=turn,
                    started=started,
                    first_event_at=first_event_at,
                )
                yield replace(chunk, turn=turn)


def registry_for(workspace: Path) -> ToolRegistry:
    available = {
        getattr(func, "__name__", ""): func
        for func in ai.toolkits.files(root=str(workspace), allow_write=True)
    }
    for func in mobile_tool_functions():
        available[func.__name__] = func
    requested = tuple(
        name.strip()
        for name in os.environ.get(
            "MODEL_SPELUNKER_PROJECTED_TOOLS", "read_file,write_file"
        ).split(",")
        if name.strip()
    )
    missing = [name for name in requested if name not in available]
    if missing:
        raise RuntimeError(f"OpenWorker projected toolkit missing required tools: {missing}")

    registry = ToolRegistry()
    for name in requested:
        registry.register(available[name])
    if registry.names() != list(requested):
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
    write_target = os.environ.get("MODEL_SPELUNKER_WRITE_TARGET", "value.txt")
    target = (workspace / write_target).resolve()
    registry = registry_for(workspace)
    permissions = PermissionEngine(
        workspace_root=workspace,
        mode=Mode.CUSTOM,
        auto_allow_tools={
            name for name in registry.names() if name.startswith("mobile_")
        },
    )
    compatible = {
        "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"),
        "google": ("GOOGLE_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/"),
        "nvidia": ("NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1"),
        "mlx": (
            "MODEL_SPELUNKER_MLX_API_KEY",
            os.environ.get(
                "MODEL_SPELUNKER_MLX_BASE_URL",
                "http://127.0.0.1:8080/v1",
            ),
        ),
    }
    if _PROVIDER in compatible:
        from coworker.providers.openai_provider import OpenAIProvider

        key_name, base_url = compatible[_PROVIDER]
        delegate = OpenAIProvider(
            api_key=os.environ[key_name],
            base_url=base_url,
        )
        engine_model = _BARE_MODEL
    else:
        delegate = ProviderRouter(secrets=None, default_provider="openai")
        engine_model = MODEL

    provider = CapabilityEnforcingProvider(delegate)

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
        model=engine_model,
        approver=approver,
        max_iterations=MAX_ITERATIONS,
        model_settings=MODEL_SETTINGS,
    )

    counts: Counter[str] = Counter()
    usage_totals: Counter[str] = Counter()
    async for event in engine.run(instruction):
        event_type = str(event.type)
        counts[event_type] += 1
        if event_type not in {
            "EventType.REASONING_DELTA",
            "EventType.ASSISTANT_DELTA",
        }:
            payload = dict(event.data or {})
            compact = {"type": event_type}
            for key in ("tool_calls", "status", "error", "error_type", "iterations", "usage"):
                if key in payload:
                    compact[key] = payload[key]
            usage = payload.get("usage")
            if isinstance(usage, dict):
                for key in ("input", "output", "cache_read", "cache_write"):
                    value = usage.get(key)
                    if isinstance(value, int) and value >= 0:
                        usage_totals[key] += value
            print("OPENWORKER_EVENT=" + json.dumps(compact, sort_keys=True), flush=True)

    summary = {
        "model": MODEL,
        "model_settings": MODEL_SETTINGS,
        "max_iterations": MAX_ITERATIONS,
        "projection": registry.names(),
        "tool_calls": tool_names(engine.messages),
        "approval_count": len(approvals),
        "approvals": approvals,
        "suppressed_speculative_batches": provider.suppressed_batches,
        "event_counts": dict(counts),
        "target_exists": target.is_file(),
    }
    provider.enrich_openrouter_generations()
    usage_summary = {
        "input": int(usage_totals.get("input", 0)),
        "output": int(usage_totals.get("output", 0)),
        "cache_read": int(usage_totals.get("cache_read", 0)),
        "cache_write": int(usage_totals.get("cache_write", 0)),
    }
    summary["usage"] = usage_summary
    summary["mobile_actions"] = mobile_action_log()
    print(
        "MODEL_SPELUNKER_MOBILE_ACTIONS="
        + json.dumps(summary["mobile_actions"], sort_keys=True),
        flush=True,
    )
    print("OPENWORKER_SUMMARY=" + json.dumps(summary, sort_keys=True), flush=True)
    print("MODEL_SPELUNKER_USAGE=" + json.dumps(usage_summary, sort_keys=True), flush=True)
    print(f"MODEL_SPELUNKER_TOOL_CALLS={len(summary['tool_calls'])}", flush=True)
    public_observations = [
        {key: value for key, value in observation.items() if not key.startswith("_")}
        for observation in provider.provider_observations
    ]
    print(
        "MODEL_SPELUNKER_PROVIDER_OBSERVATIONS="
        + json.dumps(public_observations, sort_keys=True),
        flush=True,
    )
    return 0


def main() -> int:
    instruction = sys.stdin.read().strip()
    if not instruction:
        print("missing task instruction on stdin", file=sys.stderr)
        return 2

    transcript_path = os.environ.get("MODEL_SPELUNKER_SPEECH_TRANSCRIPT_FILE")
    if transcript_path:
        path = Path(transcript_path).resolve()
        transcript = path.read_text(encoding="utf-8").strip()
        if not transcript:
            print("speech transcript is empty", file=sys.stderr)
            return 2
        if len(transcript) > 16000:
            print("speech transcript exceeds bounded context limit", file=sys.stderr)
            return 2
        digest = "sha256:" + hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        expected = os.environ.get("MODEL_SPELUNKER_SPEECH_TRANSCRIPT_SHA256")
        if expected and expected != digest:
            print("speech transcript digest mismatch", file=sys.stderr)
            return 2
        instruction = (
            instruction
            + "\n\n<speech-transcript>\n"
            + transcript
            + "\n</speech-transcript>"
        )
        print(
            "MODEL_SPELUNKER_SPEECH_CONTEXT="
            + json.dumps({"sha256": digest, "chars": len(transcript)}, sort_keys=True),
            flush=True,
        )

    provider = MODEL.split(":", 1)[0] if ":" in MODEL else "openai"
    provider_key = {
        "deepseek": "DEEPSEEK_API_KEY",
        "groq": "GROQ_API_KEY",
        "google": "GOOGLE_API_KEY",
        "nvidia": "NVIDIA_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "mlx": "MODEL_SPELUNKER_MLX_API_KEY",
    }.get(provider)
    known_keys = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OLLAMA_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "NVIDIA_API_KEY",
        "OPENROUTER_API_KEY",
        "MODEL_SPELUNKER_MLX_API_KEY",
    )
    present = [name for name in known_keys if os.environ.get(name)]
    disallowed = [name for name in present if name != provider_key]
    if disallowed:
        print(
            "crossover received credentials unrelated to selected provider: "
            + ", ".join(disallowed),
            file=sys.stderr,
        )
        return 2
    if provider_key and not os.environ.get(provider_key):
        print(f"selected provider requires {provider_key}", file=sys.stderr)
        return 2
    if provider_key is None and present:
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
