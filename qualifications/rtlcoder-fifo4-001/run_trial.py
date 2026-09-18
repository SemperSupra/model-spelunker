#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from specialist_adapter import generate_verilog as specialist_generate

PLAN_PATH = Path(os.environ.get("TRIAL_PLAN", "plan.json"))
RESULT_PATH = Path(os.environ.get("RESULT_JSON", "result.json"))
TRACE_LIMIT = 6000


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_cmd(args: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str]:
    proc = subprocess.run(
        args, cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=timeout, check=False
    )
    return proc.returncode, proc.stdout[-TRACE_LIMIT:]


def prepare_fixture(root: Path, plan: dict[str, Any]) -> None:
    source = (PLAN_PATH.parent / plan["workload"]["testbench_path"]).resolve()
    if not source.is_file():
        raise RuntimeError(f"fixed FIFO testbench missing: {source}")
    shutil.copyfile(source, root / "tb.sv")


def oracle(root: Path) -> tuple[bool, str]:
    if not (root / "solution.v").is_file():
        return False, "solution.v missing"
    rc, out = run_cmd(
        ["iverilog", "-g2012", "-s", "tb", "-o", "sim", "solution.v", "tb.sv"], root
    )
    if rc != 0:
        return False, "compile failed\n" + out
    rc, out = run_cmd(["vvp", "sim"], root)
    return rc == 0 and "PASS" in out, out


def base_result(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "specialist-amplification-result",
        "trial_id": plan["trial_id"],
        "plan_sha256": hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "specialist_identity": {
            "candidate_id": plan["specialist"]["candidate_id"],
            "expected_gguf_sha256": plan["specialist"]["sha256"],
            "resolved_gguf_sha256": os.environ.get("RTLCODER_SHA256", ""),
            "identity_match": os.environ.get("RTLCODER_SHA256", "") == plan["specialist"]["sha256"],
        },
        "fixture_identity": plan["workload"].get("fixture_identity"),
        "smoke": None,
        "integrated": None,
        "execution_disposition": "in_progress",
        "scientific_disposition": "not_supported",
    }


def run_smoke(plan: dict[str, Any]) -> dict[str, Any]:
    result = base_result(plan)
    with tempfile.TemporaryDirectory(prefix="rtlcoder-smoke-") as td:
        root = Path(td)
        prepare_fixture(root, plan)
        started = time.monotonic()
        error = None
        generated = ""
        try:
            generated = specialist_generate(plan["workload"]["task"])
            (root / "solution.v").write_text(generated, encoding="utf-8")
            passed, detail = oracle(root)
        except Exception as exc:
            passed = False
            detail = f"{type(exc).__name__}: {exc}"
            error = detail
        elapsed = time.monotonic() - started

    result["smoke"] = {
        "passed": bool(passed),
        "wall_seconds": round(elapsed, 3),
        "generated_bytes": len(generated.encode("utf-8")),
        "generated_sha256": sha256_text(generated) if generated else None,
        "candidate_verilog": generated[-TRACE_LIMIT:] if generated else "",
        "oracle_detail": detail[-TRACE_LIMIT:],
        "error": error,
    }
    result["execution_disposition"] = "completed"
    result["scientific_disposition"] = "smoke_supported" if passed else "not_supported"
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


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


async def execute_engine(engine: Any, task: str) -> tuple[str, list[dict[str, Any]], str | None]:
    from coworker.events import EventType
    final_answer = ""
    events: list[dict[str, Any]] = []
    error = None
    try:
        async for event in engine.run(task):
            payload = {"type": event.type.value, "data": event.data}
            events.append(payload)
            if event.type == EventType.ASSISTANT_MESSAGE and event.data.get("text"):
                final_answer = str(event.data["text"])
            elif event.type == EventType.ERROR:
                error = str(event.data)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return final_answer, events, error


def run_integrated(plan: dict[str, Any]) -> dict[str, Any]:
    from coworker.engine import TurnEngine
    from coworker.permissions import Mode, PermissionEngine
    from coworker.providers.openai_provider import OpenAIProvider
    from coworker.tools.registry import ToolRegistry

    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    expected_qwen = plan["baseline"]["controller"]["expected_manifest_id_prefix"]
    resolved_qwen = os.environ.get("RESOLVED_MODEL_ID", "")
    identity_ok = (
        result["specialist_identity"]["identity_match"]
        and resolved_qwen == expected_qwen
        and os.environ.get("OPENWORKER_REVISION", "") == plan["baseline"]["framework"]["revision"]
    )

    trace: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="rtlcoder-integrated-") as td:
        root = Path(td)
        prepare_fixture(root, plan)
        registry = ToolRegistry()

        def record(name: str, arguments: dict[str, Any], result_text: str) -> str:
            trace.append({
                "step": len(trace) + 1,
                "tool": name,
                "arguments": arguments,
                "result": str(result_text)[-TRACE_LIMIT:],
            })
            return result_text

        def read_spec() -> str:
            return record("read_spec", {}, plan["workload"]["task"])

        def generate_verilog(spec: str) -> str:
            rtl = specialist_generate(spec)
            return record(
                "generate_verilog",
                {"spec_sha256": sha256_text(spec)},
                rtl,
            )

        def write_solution(verilog: str) -> str:
            text = str(verilog).strip()
            fenced = re.search(r"```(?:systemverilog|verilog|sv)?\s*(.*?)```", text, re.I | re.S)
            if fenced:
                text = fenced.group(1).strip()
            text += "\n"
            (root / "solution.v").write_text(text, encoding="utf-8")
            return record("write_solution", {"bytes": len(text.encode("utf-8"))}, "solution.v written")

        def run_tests() -> str:
            passed, detail = oracle(root)
            return record("run_tests", {}, ("PASS\n" if passed else "FAIL\n") + detail)

        registry.register(read_spec, schema=schema(
            "read_spec", "Return the exact bounded RTL task specification."
        ))
        registry.register(generate_verilog, schema=schema(
            "generate_verilog",
            "Ask the bounded RTLCoder specialist to generate candidate RTL for a supplied specification. The specialist has no file, shell, test, or network-tool authority.",
            {"spec": {"type": "string", "description": "The exact RTL specification to implement."}},
            ["spec"],
        ))
        registry.register(write_solution, schema=schema(
            "write_solution", "Write candidate SystemVerilog to solution.v.",
            {"verilog": {"type": "string", "description": "Complete synthesizable SystemVerilog source."}},
            ["verilog"],
        ))
        registry.register(run_tests, schema=schema(
            "run_tests", "Compile solution.v with the fixed validated FIFO testbench and return bounded oracle output."
        ))

        controller = plan["baseline"]["controller"]
        provider = OpenAIProvider(
            api_key="ollama",
            base_url="http://127.0.0.1:11434/v1",
            default_model=controller["model"],
        )
        permissions = PermissionEngine(workspace_root=root, mode=Mode.BYPASS_APPROVALS)
        instructions = (
            "You are a bounded RTL engineer. Use only the supplied tools. "
            "A bounded RTLCoder specialist is available through generate_verilog; use it when useful, "
            "but you remain responsible for writing the candidate, running the fixed tests, and repairing "
            "or rejecting the result. Do not invent external dependencies. Finish with a short verified result."
        )
        engine = TurnEngine(
            provider=provider,
            registry=registry,
            permissions=permissions,
            model=controller["model"],
            instructions=instructions,
            max_iterations=6,
            model_settings={
                "temperature": controller["inference"]["temperature"],
                "max_tokens": controller["inference"]["max_tokens"],
                "reasoning_effort": controller["inference"]["reasoning_effort"],
            },
        )

        started = time.monotonic()
        final_answer, events, error = asyncio.run(execute_engine(engine, plan["workload"]["task"]))
        elapsed = time.monotonic() - started
        passed, detail = oracle(root)

    specialist_calls = sum(1 for x in trace if x["tool"] == "generate_verilog")
    writes = sum(1 for x in trace if x["tool"] == "write_solution")
    tests = sum(1 for x in trace if x["tool"] == "run_tests")
    result["controller_identity"] = {
        "expected_manifest_id_prefix": expected_qwen,
        "resolved_manifest_id_prefix": resolved_qwen,
        "identity_match": resolved_qwen == expected_qwen,
        "openworker_revision": os.environ.get("OPENWORKER_REVISION", ""),
    }
    result["integrated"] = {
        "passed": bool(passed),
        "specialist_invocations": specialist_calls,
        "writes": writes,
        "tests": tests,
        "tool_calls": len(trace),
        "wall_seconds": round(elapsed, 3),
        "agent_error": error,
        "oracle_detail": detail[-TRACE_LIMIT:],
        "final_answer": final_answer[-TRACE_LIMIT:],
        "tool_trace": trace,
        "engine_events": events[-120:],
    }
    result["execution_disposition"] = "completed" if identity_ok else "failed"
    result["scientific_disposition"] = (
        "supported" if identity_ok and passed and specialist_calls >= 1 else "not_supported"
    )
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["smoke", "integrated"], required=True)
    args = parser.parse_args()
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if args.phase == "smoke":
        result = run_smoke(plan)
        return 0 if result["execution_disposition"] == "completed" else 2
    result = run_integrated(plan)
    return 0 if result["execution_disposition"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
