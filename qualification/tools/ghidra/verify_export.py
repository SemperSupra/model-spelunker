#!/usr/bin/env python3
"""Independent shape/coverage oracle for a synthetic Ghidra headless export.

This proves that the source-known tool control reached Ghidra's decompiler.
It does not score actor reconstruction or general decompilation correctness.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def check(path: Path) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size > 2_500_000:
        raise ValueError("absent/oversized Ghidra export")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if set(obj) != {"schema_version", "program_name", "language", "functions", "function_limit"}:
        raise ValueError("unexpected export schema")
    if obj["schema_version"] != 1 or obj["function_limit"] != 256:
        raise ValueError("unexpected schema version or function limit")
    if obj["program_name"] != "target.bin" or not str(obj["language"]).startswith("x86:LE:64"):
        raise ValueError("incorrect program/processor")
    functions = obj["functions"]
    if not isinstance(functions, list) or not 1 <= len(functions) <= 256:
        raise ValueError("function count outside bound")
    addresses: set[str] = set()
    for f in functions:
        if not isinstance(f, dict) or set(f) != {"entry", "name", "size", "decompilation", "callees"}:
            raise ValueError("malformed function")
        if not isinstance(f["entry"], str) or not f["entry"] or f["entry"] in addresses:
            raise ValueError("missing/duplicate entry")
        addresses.add(f["entry"])
        if not isinstance(f["name"], str) or not f["name"] or type(f["size"]) is not int or f["size"] <= 0:
            raise ValueError("function name/body invalid")
        if f["decompilation"] is not None and not isinstance(f["decompilation"], str):
            raise ValueError("invalid decompilation field")
        if not isinstance(f["callees"], list) or any(not isinstance(x, str) for x in f["callees"]):
            raise ValueError("invalid call edge list")
    dispatch = [f for f in functions if f["name"] == "command_dispatch"]
    if len(dispatch) != 1:
        raise ValueError("missing or ambiguous command dispatcher")
    f = dispatch[0]
    if not f["decompilation"] or "command_dispatch" not in f["decompilation"]:
        raise ValueError("dispatcher decompilation absent")
    # This source-known case has three noinline helper branches.
    # Require at least two distinct call targets, avoiding silent empty evidence.
    if len(set(f["callees"])) < 2:
        raise ValueError("missing noinline helper call edges")
    return {"status": "PASS", "program": obj["program_name"], "language": obj["language"],
            "functions_exported": len(functions), "dispatcher_entry": f["entry"],
            "dispatcher_callees": len(set(f["callees"])),
            "dispatcher_decompiled_chars": len(f["decompilation"])}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_export.py <export.json>", file=sys.stderr)
        return 2
    try:
        print(json.dumps(check(Path(sys.argv[1])), sort_keys=True))
        return 0
    except (ValueError, OSError, UnicodeError, TypeError, KeyError) as exc:
        print(f"GHIDRA_EXPORT_FAIL={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
