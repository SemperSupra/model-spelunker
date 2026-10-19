#!/usr/bin/env python3
"""Compiler-informed source-known tail-call / RE relation regression.

Public-safe C fixture only. Reproduces why Ghidra's recovered call *targets*
can exceed the count of raw CALL p-code ops in an optimized dispatcher.
No untrusted or private binary input is accepted and no artifact is uploaded.
Static compiler codegen control only; semantic native I/O is tested separately.
"""
from __future__ import annotations
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "dispatcher.c"

def dispatch_block(text: str) -> list[str]:
    lines = text.splitlines()
    anchors = [i for i, row in enumerate(lines) if re.search(r"<command_dispatch>:\s*$", row)]
    if len(anchors) != 1:
        raise ValueError("dispatcher symbol not uniquely located")
    out = []
    for row in lines[anchors[0] + 1:]:
        if not row.strip():
            break
        out.append(row)
    if not out:
        raise ValueError("dispatcher body absent")
    return out


def run() -> None:
    cc = shutil.which("clang")
    dump = shutil.which("objdump")
    strip = shutil.which("strip")
    if not (cc and dump and strip):
        raise RuntimeError("requires clang, objdump, strip")
    with tempfile.TemporaryDirectory(prefix="re-tailcall-") as d:
        root = Path(d)
        script = root / "exports.map"
        script.write_text("{ global: command_dispatch; local: *; };\n")
        rows = []
        for name, disable in [("optimized", False), ("no_sibling_calls", True)]:
            target = root / f"{name}.so"
            cmd = [cc, "-O1", "-shared", "-fPIC", "-fno-stack-protector",
                   "-fno-ident", "-Wl,--build-id=none", f"-Wl,--version-script={script}"]
            if disable:
                cmd.append("-fno-optimize-sibling-calls")
            cmd.extend([str(SOURCE), "-o", str(target)])
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
            asm = subprocess.run([dump, "-d", str(target)], check=True,
                                 capture_output=True, text=True, timeout=20).stdout
            block = dispatch_block(asm)
            calls = sum(bool(re.search(r"\bcallq?\b", row)) for row in block)
            tail_jumps = sum(bool(re.search(r"\bjmpq?\b.*<handler_fold>", row)) for row in block)
            expected_calls = 3 if disable else 2
            expected_tail = 0 if disable else 1
            if (calls, tail_jumps) != (expected_calls, expected_tail):
                raise ValueError(f"{name}: toolchain hypothesis falsified: "
                                 f"calls={calls} tail_jumps={tail_jumps}")
            subprocess.run([strip, "--strip-all", str(target)], check=True,
                           capture_output=True, text=True, timeout=20)
            rows.append({"variant": name, "call_instructions": calls,
                         "tail_jumps_to_fold": tail_jumps, "runtime_vectors_executed": 0,
                         "stripped_sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        print(json.dumps({"status": "PASS",
                          "compiler": subprocess.run([cc, "--version"], text=True,
                                                     capture_output=True, check=True).stdout.splitlines()[0],
                          "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                          "variants": rows}, indent=2, sort_keys=True))


if __name__ == "__main__":
    run()
