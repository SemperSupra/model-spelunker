#!/usr/bin/env python3
from __future__ import annotations

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

from coworker.engine import TurnEngine
from coworker.events import EventType
from coworker.permissions import Mode, PermissionEngine
from coworker.providers.openai_provider import OpenAIProvider
from coworker.tools.registry import ToolRegistry

PLAN_PATH = Path(os.environ.get("QUALIFICATION_JSON", "qualification.json"))
RESULT_PATH = Path(os.environ.get("RESULT_JSON", "result.json"))
TRACE_LIMIT = 6000
UNLOCK_CODE = 7351


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def run_cmd(args: list[str], cwd: Path, timeout: int = 20) -> tuple[int, str]:
    proc = subprocess.run(
        args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=timeout, check=False
    )
    return proc.returncode, proc.stdout[-TRACE_LIMIT:]


def sanitize_code(text: str) -> str:
    text = str(text).strip()
    fenced = re.search(r"```(?:systemverilog|verilog|sv)?\s*(.*?)```", text, re.I | re.S)
    return (fenced.group(1) if fenced else text).strip() + "\n"


def prepare_rtl_fixture(root: Path, workload: dict[str, Any]) -> None:
    testbench_path = workload.get("testbench_path")
    if testbench_path:
        source = (PLAN_PATH.parent / str(testbench_path)).resolve()
        if not source.is_file():
            raise RuntimeError(f"fixed RTL testbench missing: {source}")
        shutil.copyfile(source, root / "tb.sv")
        return

    (root / "tb.sv").write_text(
        """module tb;
  logic [3:0] bits;
  logic [2:0] count;
  integer i;
  integer expected;

  popcount4 dut(.bits(bits), .count(count));

  initial begin
    for (i = 0; i < 16; i = i + 1) begin
      bits = i[3:0];
      #1;
      expected = bits[0] + bits[1] + bits[2] + bits[3];
      if (count !== expected[2:0]) begin
        $display("FAIL bits=%0d count=%0d expected=%0d", bits, count, expected);
        $finish(1);
      end
    end
    $display("PASS");
    $finish(0);
  end
endmodule
""",
        encoding="utf-8",
    )

def rtl_oracle(root: Path) -> tuple[bool, str]:
    if not (root / "solution.v").is_file():
        return False, "solution.v missing"
    rc, out = run_cmd(
        ["iverilog", "-g2012", "-s", "tb", "-o", "sim", "solution.v", "tb.sv"], root
    )
    if rc != 0:
        return False, f"compile failed\n{out}"
    rc, out = run_cmd(["vvp", "sim"], root)
    return rc == 0 and "PASS" in out, out


def prepare_binary_fixture(root: Path) -> None:
    source = f"""#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {{
    if (argc != 2) {{
        puts("usage: challenge CODE");
        return 2;
    }}
    long value = strtol(argv[1], 0, 10);
    if (value == {UNLOCK_CODE}) {{
        puts("ACCESS GRANTED");
        return 0;
    }}
    puts("DENIED");
    return 1;
}}
"""
    (root / "challenge.c").write_text(source, encoding="utf-8")
    rc, out = run_cmd(
        ["gcc", "-O0", "-fno-pie", "-no-pie", "-fno-stack-protector",
         "-o", "challenge", "challenge.c"], root
    )
    if rc != 0:
        raise RuntimeError(f"failed to build binary fixture: {out}")
    (root / "challenge.c").unlink()


def binary_oracle(root: Path, final_answer: str, trace: list[dict[str, Any]]) -> tuple[bool, str]:
    for event in trace:
        if event.get("tool") == "try_unlock" and "ACCESS GRANTED" in str(event.get("result", "")):
            return True, "accepted candidate was verified through try_unlock"
    candidates = re.findall(r"(?<!\d)(\d{3,6})(?!\d)", final_answer)
    for candidate in reversed(candidates):
        rc, out = run_cmd(["./challenge", candidate], root)
        if rc == 0 and "ACCESS GRANTED" in out:
            return True, f"final answer candidate {candidate} verified independently"
    return False, "no accepted unlock code found in tool trace or final answer"


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


def make_registry(kind: str, task: str, root: Path, trace: list[dict[str, Any]], draft_path: Path | None = None) -> ToolRegistry:
    registry = ToolRegistry()

    def record(name: str, arguments: dict[str, Any], result: str) -> str:
        trace.append({
            "step": len(trace) + 1,
            "tool": name,
            "arguments": arguments,
            "result": str(result)[-TRACE_LIMIT:],
        })
        return result

    def read_spec() -> str:
        return record("read_spec", {}, task)

    registry.register(
        read_spec,
        schema=schema("read_spec", "Return the exact bounded task specification for this qualification run.")
    )

    if draft_path is not None:
        def read_specialist_draft() -> str:
            draft = draft_path.read_text(encoding="utf-8")
            return record(
                "read_specialist_draft",
                {"sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(), "bytes": len(draft.encode("utf-8"))},
                draft,
            )

        registry.register(
            read_specialist_draft,
            schema=schema(
                "read_specialist_draft",
                "Return the exact frozen, untrusted specialist-generated RTL draft for diagnosis and repair."
            ),
        )

    if kind == "rtl":
        def write_solution(verilog: str) -> str:
            code = sanitize_code(verilog)
            (root / "solution.v").write_text(code, encoding="utf-8")
            return record("write_solution", {"bytes": len(code.encode("utf-8"))}, "solution.v written")

        def run_tests() -> str:
            passed, detail = rtl_oracle(root)
            return record("run_tests", {}, ("PASS\n" if passed else "FAIL\n") + detail)

        registry.register(
            write_solution,
            schema=schema(
                "write_solution",
                "Write the candidate SystemVerilog implementation to solution.v.",
                {"verilog": {"type": "string", "description": "Complete synthesizable SystemVerilog source."}},
                ["verilog"],
            ),
        )
        registry.register(
            run_tests,
            schema=schema("run_tests", "Compile solution.v with the fixed testbench and return bounded test output.")
        )
        return registry

    if kind == "binary_re":
        def inspect_strings() -> str:
            _, out = run_cmd(["strings", "./challenge"], root)
            return record("inspect_strings", {}, out)

        def disassemble_main() -> str:
            _, out = run_cmd(["objdump", "-d", "-Mintel", "--disassemble=main", "./challenge"], root)
            return record("disassemble_main", {}, out)

        def try_unlock(code: int) -> str:
            rc, out = run_cmd(["./challenge", str(int(code))], root)
            return record("try_unlock", {"code": int(code)}, f"exit={rc}\n{out}")

        registry.register(
            inspect_strings,
            schema=schema("inspect_strings", "Return printable strings from the benign challenge binary.")
        )
        registry.register(
            disassemble_main,
            schema=schema("disassemble_main", "Return Intel-syntax disassembly of main from the benign challenge binary.")
        )
        registry.register(
            try_unlock,
            schema=schema(
                "try_unlock",
                "Run the benign challenge with one candidate numeric unlock code.",
                {"code": {"type": "integer", "description": "Candidate decimal unlock code recovered from the binary."}},
                ["code"],
            ),
        )
        return registry

    raise ValueError(f"unsupported workload kind: {kind}")


async def execute_engine(engine: TurnEngine, task: str) -> tuple[str, list[dict[str, Any]], str | None]:
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


def run_pairing(persona: dict[str, Any], workload: dict[str, Any], repetition: int) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="persona-openworker-qualification-") as td:
        root = Path(td)
        if workload["kind"] == "rtl":
            prepare_rtl_fixture(root, workload)
        elif workload["kind"] == "binary_re":
            prepare_binary_fixture(root)
        else:
            raise ValueError(f"unsupported workload kind: {workload['kind']}")

        draft_path = None
        if workload.get("draft_path"):
            draft_path = (PLAN_PATH.parent / str(workload["draft_path"])).resolve()
            if not draft_path.is_file():
                raise RuntimeError(f"frozen specialist draft missing: {draft_path}")
        registry = make_registry(workload["kind"], workload["task"], root, trace, draft_path)
        settings = persona["controller"]["inference"]
        provider = OpenAIProvider(
            api_key="ollama",
            base_url="http://127.0.0.1:11434/v1",
            default_model=persona["controller"]["model"],
        )
        permissions = PermissionEngine(workspace_root=root, mode=Mode.BYPASS_APPROVALS)
        engine = TurnEngine(
            provider=provider,
            registry=registry,
            permissions=permissions,
            model=persona["controller"]["model"],
            instructions=persona["instructions"],
            max_iterations=persona["limits"]["max_steps"],
            model_settings={
                "temperature": settings["temperature"],
                "max_tokens": settings["max_tokens"],
                "reasoning_effort": settings["reasoning_effort"],
            },
        )

        started = time.monotonic()
        final_answer, engine_events, error = asyncio.run(execute_engine(engine, workload["task"]))
        elapsed = time.monotonic() - started

        if workload["kind"] == "rtl":
            passed, oracle_detail = rtl_oracle(root)
        else:
            passed, oracle_detail = binary_oracle(root, final_answer, trace)

        draft_required = bool(workload.get("draft_path"))
        draft_reads = sum(1 for event in trace if event.get("tool") == "read_specialist_draft")
        scientific_pass = bool(passed) and (not draft_required or draft_reads >= 1)

        return {
            "persona_id": persona["persona_id"],
            "persona_sha256": canonical_hash(persona),
            "workload_id": workload["workload_id"],
            "workload_sha256": canonical_hash(workload),
            "repetition": repetition,
            "passed": scientific_pass,
            "oracle_passed": bool(passed),
            "draft_required": draft_required,
            "draft_reads": draft_reads,
            "wall_seconds": round(elapsed, 3),
            "final_answer": final_answer[-TRACE_LIMIT:],
            "agent_error": error,
            "oracle_detail": oracle_detail[-TRACE_LIMIT:],
            "tool_trace": trace,
            "engine_events": engine_events[-100:],
        }


def main() -> int:
    plan_bytes = PLAN_PATH.read_bytes()
    plan = json.loads(plan_bytes)
    personas = {p["persona_id"]: p for p in plan["personas"]}
    workloads = {w["workload_id"]: w for w in plan["workloads"]}

    resolved_model_id = os.environ.get("RESOLVED_MODEL_ID", "")
    resolved_ollama_version = os.environ.get("RESOLVED_OLLAMA_VERSION", "")
    openworker_revision = os.environ.get("OPENWORKER_REVISION", "")
    expected_ids = {p["controller"]["expected_manifest_id_prefix"] for p in plan["personas"]}
    expected_revisions = {p["framework"]["revision"] for p in plan["personas"]}
    reasoning_efforts = {p["controller"]["inference"]["reasoning_effort"] for p in plan["personas"]}
    identity_ok = (
        len(expected_ids) == 1
        and resolved_model_id in expected_ids
        and len(expected_revisions) == 1
        and openworker_revision in expected_revisions
        and reasoning_efforts == {"none"}
    )

    runs: list[dict[str, Any]] = []
    if identity_ok:
        for pairing in plan["pairings"]:
            persona = personas[pairing["persona_id"]]
            workload = workloads[pairing["workload_id"]]
            for repetition in range(1, int(plan["repetitions"]) + 1):
                runs.append(run_pairing(persona, workload, repetition))

    by_pairing: dict[str, dict[str, int]] = {}
    for run in runs:
        key = f"{run['persona_id']}::{run['workload_id']}"
        bucket = by_pairing.setdefault(key, {"attempted": 0, "passed": 0})
        bucket["attempted"] += 1
        bucket["passed"] += int(run["passed"])

    required_attempts = len(plan["pairings"]) * int(plan["repetitions"])
    execution_complete = identity_ok and len(runs) == required_attempts
    qualification_supported = (
        execution_complete
        and len(by_pairing) == len(plan["pairings"])
        and all(stats["passed"] >= 1 for stats in by_pairing.values())
    )

    result = {
        "schema_version": 1,
        "record_type": "persona-qualification-result",
        "qualification_id": plan["qualification_id"],
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "execution_disposition": "completed" if execution_complete else "failed",
        "scientific_disposition": "supported" if qualification_supported else "not_supported",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "resolved_framework": {
            "name": "openworker",
            "revision": openworker_revision,
        },
        "resolved_controller": {
            "ollama_version": resolved_ollama_version,
            "model_manifest_id_prefix": resolved_model_id,
            "identity_match": identity_ok,
            "reasoning_effort": next(iter(reasoning_efforts), None),
        },
        "pairing_summary": by_pairing,
        "runs": runs,
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if execution_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
