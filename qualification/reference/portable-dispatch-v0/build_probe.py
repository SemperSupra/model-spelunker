#!/usr/bin/env python3
"""Build and independently validate source-known multi-ISA object RDT&E fixtures.

No SDK, emulation, network, binaries in Git, or runtime-specific execution.
Compiles the same freestanding C source to target *objects* only.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "dispatcher.c"
TARGETS = {
    "linux-x86_64-elf": ("x86_64-unknown-linux-gnu", "elf", 62),
    "linux-aarch64-elf": ("aarch64-unknown-linux-gnu", "elf", 183),
    "windows-x86_64-coff": ("x86_64-pc-windows-msvc", "coff", 0x8664),
    "macos-arm64-macho": ("arm64-apple-macos13", "macho", 0x0100000c),
    "wasm32": ("wasm32-unknown-unknown", "wasm", None),
    "cortex-m3-elf": ("armv7m-none-eabi", "elf", 40),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fmt_identity(data: bytes) -> tuple[str, int | None]:
    if data.startswith(b"\x7fELF") and len(data) >= 20:
        if data[5] not in (1, 2):
            raise ValueError("unsupported ELF endian field")
        machine = struct.unpack_from("<H" if data[5] == 1 else ">H", data, 18)[0]
        return "elf", machine
    if data.startswith(b"\xcf\xfa\xed\xfe") and len(data) >= 8:
        return "macho", struct.unpack_from("<I", data, 4)[0]
    if data.startswith(b"\xfe\xed\xfa\xcf") and len(data) >= 8:
        return "macho", struct.unpack_from(">I", data, 4)[0]
    if data.startswith(b"\x00asm\x01\x00\x00\x00"):
        return "wasm", None
    if len(data) >= 20 and data[2:4] != b"\x00\x00":
        machine, sections = struct.unpack_from("<HH", data, 0)
        if machine in {0x8664, 0x14c, 0xaa64} and sections > 0:
            return "coff", machine
    raise ValueError("unrecognized or invalid object header")


def oracle(command: int, value: int) -> int:
    mask = 0xffffffff
    if command == 0x11:
        return (((value * 33) ^ 0x5a5a5a5a) + 17) & mask
    if command == 0x29:
        rot = ((value << 7) | (value >> 25)) & mask
        return rot ^ 0xa55a0ff0
    if command == 0x3d:
        out = 0x7f4a7c15
        for i in range(4):
            out = (((out << 3) | (out >> 29)) ^ (value + i * 17)) & mask
        return out
    return mask


def run(*, cc: str, output: Path, no_native: bool) -> dict:
    compiler = shutil.which(cc)
    if not compiler:
        raise RuntimeError(f"compiler unavailable: {cc}")
    version = subprocess.run([compiler, "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    evidence: dict = {"schema_version": 1, "source_sha256": sha256(SOURCE), "compiler": version, "targets": {}}
    for name, (triple, fmt, machine) in TARGETS.items():
        dest = output / f"{name}.o"
        cmd = [compiler, f"--target={triple}", "-O1", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-c", str(SOURCE), "-o", str(dest)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode:
            evidence["targets"][name] = {"status": "COMPILE_FAILED", "returncode": proc.returncode, "stderr": proc.stderr[-1000:]}
            continue
        observed_fmt, observed_machine = fmt_identity(dest.read_bytes())
        passed = (fmt, machine) == (observed_fmt, observed_machine)
        evidence["targets"][name] = {"status": "PASS" if passed else "ORACLE_FAILED", "triple": triple, "format": observed_fmt,
                                     "machine": observed_machine, "source_sha256": sha256(SOURCE), "object_sha256": sha256(dest),
                                     "size_bytes": dest.stat().st_size}
    if not no_native and sys.platform.startswith("linux"):
        lib = output / "libdispatcher.so"
        proc = subprocess.run([compiler, "-O1", "-shared", "-fPIC", str(SOURCE), "-o", str(lib)], capture_output=True, text=True, timeout=90)
        if proc.returncode:
            evidence["native_oracle"] = {"status": "COMPILE_FAILED", "stderr": proc.stderr[-1000:]}
        else:
            fn = ctypes.CDLL(str(lib)).command_dispatch
            fn.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
            fn.restype = ctypes.c_uint32
            cases = [(op, value) for op in (0x11, 0x29, 0x3d, 0xff) for value in (0, 1, 0x12345678, 0xffffffff)]
            actual = [fn(op, value) for op, value in cases]
            expected = [oracle(op, value) for op, value in cases]
            evidence["native_oracle"] = {"status": "PASS" if actual == expected else "ORACLE_FAILED", "vectors": len(cases), "library_sha256": sha256(lib)}
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", default="clang")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-native", action="store_true")
    args = parser.parse_args()
    if args.output is None:
        with tempfile.TemporaryDirectory(prefix="re-reference-") as path:
            result = run(cc=args.compiler, output=Path(path), no_native=args.no_native)
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        result = run(cc=args.compiler, output=args.output, no_native=args.no_native)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if all(row["status"] == "PASS" for row in result["targets"].values()) and result.get("native_oracle", {"status":"PASS"})["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
