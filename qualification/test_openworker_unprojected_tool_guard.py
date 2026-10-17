#!/usr/bin/env python3
"""Unit tests for out-of-projection tool-call salvage and stray markup sanitization."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS_DIR = ROOT / "qualification" / "adapters"
if str(ADAPTERS_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTERS_DIR))

try:
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
except ImportError:
    # Provide minimal protocol-compatible stubs when running outside an OpenWorker venv.
    @dataclass
    class ToolCall:
        id: str = ""
        name: str = ""
        arguments: dict[str, Any] = field(default_factory=dict)

    @dataclass
    class AssistantTurn:
        text: Optional[str] = None
        tool_calls: list[Any] = field(default_factory=list)
        finish_reason: Optional[str] = None
        raw: Any = None
        reasoning: Optional[str] = None
        usage: Any = None

    @dataclass
    class ModelCapabilities:
        parallel_tool_calls: bool = False

    class ProviderClient:
        pass

    ai_mod = types.ModuleType("aisuite")
    sys.modules.setdefault("aisuite", ai_mod)

    cw_mod = types.ModuleType("coworker")
    cw_engine = types.ModuleType("coworker.engine")
    cw_engine.ApprovalOutcome = object
    cw_engine.PermissionRequest = object
    cw_engine.TurnEngine = object
    cw_perm = types.ModuleType("coworker.permissions")
    cw_perm.Mode = object
    cw_perm.PermissionEngine = object
    cw_prov = types.ModuleType("coworker.providers")
    cw_prov.AssistantTurn = AssistantTurn
    cw_prov.ModelCapabilities = ModelCapabilities
    cw_prov.ProviderClient = ProviderClient
    cw_router = types.ModuleType("coworker.providers.router")
    cw_router.ProviderRouter = object
    cw_tools = types.ModuleType("coworker.tools")
    cw_tools.ToolRegistry = object
    cw_oai = types.ModuleType("coworker.providers.openai_provider")
    cw_oai._LEAKED_TOOL_SYNTAX = (
        "<tool_call>",
        "</tool_call>",
        "<function=",
        "</function>",
        "<parameter=",
        "</parameter>",
        "<function_calls>",
        "<invoke ",
    )
    _FN_RE = re.compile(
        r"<function\s*=\s*(?P<name>[^>\s]+)\s*>(?P<body>.*?)</function\s*>",
        re.IGNORECASE | re.DOTALL,
    )

    def _salvage_tool_calls_from_text(content: str, tools: Any = None) -> list[ToolCall]:
        allowed = (
            {t.get("function", {}).get("name") for t in tools if isinstance(t, dict)}
            if tools is not None
            else None
        )
        out: list[ToolCall] = []
        for m in _FN_RE.finditer(content or ""):
            name = m.group("name").strip()
            if allowed is not None and name not in allowed:
                continue
            out.append(ToolCall(id="call_1", name=name, arguments={}))
        return out

    def looks_like_unparsed_tool_call(text: Optional[str], tools: Any = None) -> bool:
        if not tools or not text:
            return False
        low = text.lower()
        return any(tok in low for tok in cw_oai._LEAKED_TOOL_SYNTAX)

    cw_oai._salvage_tool_calls_from_text = _salvage_tool_calls_from_text
    cw_oai.looks_like_unparsed_tool_call = looks_like_unparsed_tool_call

    sys.modules["coworker"] = cw_mod
    sys.modules["coworker.engine"] = cw_engine
    sys.modules["coworker.permissions"] = cw_perm
    sys.modules["coworker.providers"] = cw_prov
    sys.modules["coworker.providers.router"] = cw_router
    sys.modules["coworker.providers.openai_provider"] = cw_oai
    sys.modules["coworker.tools"] = cw_tools

import openworker_projected as ow  # noqa: E402


class _FakeDelegate(ProviderClient):
    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(parallel_tool_calls=False)

    def complete(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    def stream(self, **kwargs: Any) -> Any:
        raise NotImplementedError


class OpenWorkerUnprojectedToolGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = ow.CapabilityEnforcingProvider(_FakeDelegate())
        self.tools = [
            {
                "type": "function",
                "function": {"name": "read_file", "parameters": {"type": "object"}},
            },
            {
                "type": "function",
                "function": {"name": "write_file", "parameters": {"type": "object"}},
            },
        ]

    def test_unprojected_xml_tool_call_is_salvaged_for_engine_denial(self) -> None:
        turn = AssistantTurn(
            text="<tool_call><function=bash><parameter=command>pytest</parameter></function></tool_call>",
            tool_calls=[],
        )
        enforced = self.provider._enforce("ollama:qwen3-coder:30b", turn, tools=self.tools)
        self.assertIsNone(enforced.text)
        self.assertEqual(len(enforced.tool_calls), 1)
        self.assertEqual(enforced.tool_calls[0].name, "bash")
        self.assertEqual(self.provider.unprojected_tool_calls, [{"names": ["bash"]}])

    def test_stray_tool_markup_without_call_is_stripped(self) -> None:
        turn = AssistantTurn(
            text="I have updated src/retry.py.</tool_call>",
            tool_calls=[],
        )
        enforced = self.provider._enforce("ollama:qwen3-coder:30b", turn, tools=self.tools)
        self.assertEqual(enforced.tool_calls, [])
        self.assertEqual(enforced.text, "I have updated src/retry.py.")
        self.assertEqual(self.provider.stripped_stray_tool_markup, 1)

    def test_tool_names_filters_to_projected_allowlist(self) -> None:
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"function": {"name": "read_file"}},
                    {"function": {"name": "bash"}},
                    {"function": {"name": "write_file"}},
                ],
            }
        ]
        self.assertEqual(
            ow.tool_names(messages, {"read_file", "write_file"}),
            ["read_file", "write_file"],
        )


if __name__ == "__main__":
    unittest.main()
