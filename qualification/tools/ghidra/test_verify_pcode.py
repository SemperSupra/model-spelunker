#!/usr/bin/env python3
"""Fail-closed negative controls for the p-code / Ghidra baseline comparator."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from verify_pcode import check


def valid() -> tuple[dict, dict]:
    name = "command_dispatch"
    entry = "00101150"
    base = {"program_name": "target.bin", "language": "x86:LE:64:default",
            "functions": [{"entry": entry, "name": name}]}
    pcode = {"schema_version": 1, "pcode_level": "raw_instruction",
             "program_name": "target.bin", "language": "x86:LE:64:default",
             "functions": [{"entry": entry, "name": name, "instruction_count": 2,
                            "pcode_total": 3, "sampled": 3, "truncated": False,
                            "histogram": {"CALL": 1, "CBRANCH": 1, "INT_XOR": 1},
                            "ops": [
                                {"instruction": entry, "opcode": op, "output": "(unique,0x4,4)",
                                 "inputs": ["(register,0x0,8)"]}
                                for op in ("CALL", "CBRANCH", "INT_XOR")
                            ]}],
             "function_limit": 256, "global_pcode_total": 3}
    return base, pcode


def run() -> int:
    base, pcode = valid()
    with tempfile.TemporaryDirectory(prefix="re-pcode-oracle-") as d:
        p = Path(d)
        b, v = p / "baseline.json", p / "pcode.json"
        def evaluated(a: dict, x: dict) -> bool:
            b.write_text(json.dumps(a), encoding="utf-8")
            v.write_text(json.dumps(x), encoding="utf-8")
            try:
                check(b, v)
                return True
            except (ValueError, TypeError, KeyError, OSError, OverflowError, UnicodeError):
                return False
        assert evaluated(base, pcode), "known-good rejected"
        negative = []
        variant = copy.deepcopy(pcode); variant["pcode_level"] = "decompiler_high"
        negative.append(("wrong representation", variant))
        variant = copy.deepcopy(pcode); variant["global_pcode_total"] = 4
        negative.append(("wrong aggregate", variant))
        variant = copy.deepcopy(pcode); variant["functions"][0]["histogram"]["CALL"] = 2
        negative.append(("histogram inflation", variant))
        variant = copy.deepcopy(pcode); variant["functions"][0]["ops"][0]["opcode"] = "FAKE"
        negative.append(("sample not in histogram", variant))
        variant = copy.deepcopy(pcode); variant["functions"][0]["name"] = "helper_not_dispatch"
        negative.append(("function attribution drift", variant))
        variant = copy.deepcopy(pcode); variant["functions"][0]["truncated"] = True
        negative.append(("invalid truncation status", variant))
        variant = copy.deepcopy(pcode); variant["functions"][0]["sampled"] = True
        negative.append(("boolean count", variant))
        variant = copy.deepcopy(pcode); variant["functions"][0]["ops"][1]["output"] = "X" * 121
        negative.append(("oversized operand", variant))
        variant = copy.deepcopy(pcode); variant["functions"][0]["ops"][1]["inputs"].append(None)
        negative.append(("invalid operand", variant))
        variant = copy.deepcopy(pcode); variant["functions"][0]["ops"].pop()
        negative.append(("missing sampled operation", variant))
        variant = copy.deepcopy(pcode); variant["functions"][0]["histogram"] = {"COPY": 3}
        negative.append(("missing expected relevant operations", variant))
        for label, changed in negative:
            assert not evaluated(base, changed), "bad p-code record accepted: " + label
    print(f"PASS raw p-code verifier known-good + {len(negative)} negative controls")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
