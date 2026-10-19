#!/usr/bin/env python3
"""Independent structural oracle for bounded Ghidra raw-instruction p-code.

Does NOT assert that p-code alone reconstructs runtime behavior or that an
LLM improved. Exact function identity is compared against the proven baseline.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ENTRY = re.compile(r"^[0-9a-fA-F]{4,16}$")
OPCODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
FUNCTION_FIELDS = {"entry", "name", "instruction_count", "pcode_total",
                   "sampled", "truncated", "histogram", "ops"}
OP_FIELDS = {"instruction", "opcode", "output", "inputs"}


def unsigned_int(x: object) -> bool:
    return type(x) is int and x >= 0


def check(baseline_path: Path, pcode_path: Path) -> dict:
    if not baseline_path.is_file() or baseline_path.stat().st_size > 2_500_000:
        raise ValueError("invalid baseline export")
    if not pcode_path.is_file() or pcode_path.stat().st_size > 2_500_000:
        raise ValueError("invalid bounded pcode export")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    artifact = json.loads(pcode_path.read_text(encoding="utf-8"))
    if set(artifact) != {"schema_version", "pcode_level", "program_name",
                         "language", "functions", "function_limit", "global_pcode_total"}:
        raise ValueError("unexpected pcode schema")
    if type(artifact["schema_version"]) is not int or artifact["schema_version"] != 1:
        raise ValueError("schema version mismatch")
    if artifact["pcode_level"] != "raw_instruction":
        raise ValueError("pcode must be raw instruction-level, not elevated to decompiler semantics")
    if artifact["program_name"] != baseline.get("program_name") or artifact["language"] != baseline.get("language"):
        raise ValueError("program/language differs from control")
    if artifact["function_limit"] != 256 or not unsigned_int(artifact["global_pcode_total"]):
        raise ValueError("invalid bounds")
    baseline_functions = baseline.get("functions")
    functions = artifact["functions"]
    if not isinstance(baseline_functions, list) or not isinstance(functions, list):
        raise ValueError("invalid function collections")
    if not 1 <= len(functions) == len(baseline_functions) <= 256:
        raise ValueError("missing or extra function")
    identity = {(f["entry"], f["name"]) for f in baseline_functions}
    if len(identity) != len(baseline_functions):
        raise ValueError("duplicate baseline")
    observed = set()
    total = 0
    semantic_op_count = 0
    dispatch = None
    for f in functions:
        if not isinstance(f, dict) or set(f) != FUNCTION_FIELDS:
            raise ValueError("bad function record")
        if (f["entry"], f["name"]) not in identity or (f["entry"], f["name"]) in observed:
            raise ValueError("pcode function identity drift")
        observed.add((f["entry"], f["name"]))
        if not ENTRY.fullmatch(f["entry"]):
            raise ValueError("invalid entry")
        if not all(unsigned_int(f[field]) for field in ("instruction_count", "pcode_total", "sampled")):
            raise ValueError("invalid counts")
        if f["instruction_count"] > 1024 or f["sampled"] > 256 or f["sampled"] > f["pcode_total"]:
            raise ValueError("limit exceeded")
        if type(f["truncated"]) is not bool or f["truncated"] != (f["sampled"] < f["pcode_total"]):
            raise ValueError("truncation status invalid")
        hist = f["histogram"]
        ops = f["ops"]
        if not isinstance(hist, dict) or not isinstance(ops, list) or len(ops) != f["sampled"]:
            raise ValueError("histogram/sample mismatch")
        if not all(isinstance(k, str) and OPCODE.fullmatch(k) and unsigned_int(v) and v > 0
                   for k, v in hist.items()):
            raise ValueError("bad opcode histogram")
        if sum(hist.values()) != f["pcode_total"]:
            raise ValueError("pcode total differs from histogram")
        if f["pcode_total"] and f["instruction_count"] == 0:
            raise ValueError("pcode without instructions")
        seen_ops = Counter()
        for op in ops:
            if not isinstance(op, dict) or set(op) != OP_FIELDS:
                raise ValueError("bad pcode sample")
            if not isinstance(op["instruction"], str) or not ENTRY.fullmatch(op["instruction"]):
                raise ValueError("bad instruction address")
            name = op["opcode"]
            if not isinstance(name, str) or not OPCODE.fullmatch(name):
                raise ValueError("bad opcode")
            if op["output"] is not None and (not isinstance(op["output"], str) or len(op["output"]) > 120):
                raise ValueError("bad output varnode")
            if not isinstance(op["inputs"], list) or len(op["inputs"]) > 8 or any(
                not isinstance(v, str) or len(v) > 120 for v in op["inputs"]
            ):
                raise ValueError("bad input varnode")
            seen_ops[name] += 1
        if any(n > hist.get(k, 0) for k, n in seen_ops.items()):
            raise ValueError("sample exceeds opcode histogram")
        total += f["pcode_total"]
        semantic_op_count += sum(hist.get(k, 0) for k in ("CBRANCH", "CALL", "INT_XOR", "INT_ADD", "INT_MULT"))
        if f["name"] == "command_dispatch":
            dispatch = f
    if len(observed) != len(identity) or total != artifact["global_pcode_total"] or total > 20000:
        raise ValueError("global total/identity invalid")
    if dispatch is None or dispatch["pcode_total"] < 1 or dispatch["sampled"] < 1:
        raise ValueError("missing dispatcher pcode")
    if semantic_op_count < 3:
        raise ValueError("missing relevant operational evidence")
    return {"status": "PASS", "functions_matched": len(observed),
            "pcode_ops": total, "dispatcher_pcode_ops": dispatch["pcode_total"],
            "dispatcher_sampled": dispatch["sampled"],
            "dispatcher_opcodes": dispatch["histogram"],
            "semantic_op_count": semantic_op_count}


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify_pcode.py <baseline.json> <pcode.json>", file=sys.stderr)
        return 2
    try:
        print(json.dumps(check(Path(sys.argv[1]), Path(sys.argv[2])), sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError, OverflowError, UnicodeError) as exc:
        print(f"GHIDRA_PCODE_INVALID={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
