#!/usr/bin/env python3
"""Build public-safe reference/target Windows PE32+ DLLs for FID research.

Runs on an admitted Linux runner with Clang, LLD and GNU binutils. Never executes PE.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "windows_reference.c"
EXPECTED_REFERENCE = {"re_dispatch", "re_lib_mix", "re_lib_crc",
                      "re_lib_scramble", "re_lib_unrelated"}
EXPECTED_TARGET = {"re_dispatch"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def call(args: list[str], timeout: int = 90) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=timeout).stdout


def identity(path: Path) -> str:
    data = path.read_bytes()
    if data[:2] != b"MZ" or len(data) < 256:
        raise ValueError("missing MZ header")
    off = struct.unpack_from("<I", data, 0x3c)[0]
    if data[off:off + 4] != b"PE\x00\x00":
        raise ValueError("missing PE header")
    machine = struct.unpack_from("<H", data, off + 4)[0]
    opt_magic = struct.unpack_from("<H", data, off + 24)[0]
    if (machine, opt_magic) != (0x8664, 0x20b):
        raise ValueError("not an x64 PE32+ image")
    return "PE32+ x86_64 DLL"


def exports(dump: str) -> set[str]:
    section = dump.split("[Ordinal/Name Pointer] Table", 1)
    if len(section) != 2:
        raise ValueError("PE export name table missing")
    section = section[1].split("There is a", 1)[0]
    return set(re.findall(r"\[\s*\d+\]\s+\+base\[\s*\d+\]\s+\w+\s+(re_\w+)", section))


def build(out: Path) -> dict:
    clang = shutil.which("clang") or shutil.which("clang-18")
    link = shutil.which("lld-link") or shutil.which("lld-link-18")
    dump = shutil.which("objdump")
    if not (clang and link and dump):
        raise RuntimeError("Clang / lld-link / GNU objdump needed; no downloader")
    out.mkdir(parents=True, exist_ok=True)
    obj = out / "windows_reference.obj"
    call([clang, "--target=x86_64-pc-windows-msvc", "-O1", "-ffunction-sections",
          "-ffreestanding", "-fno-stack-protector", "-g0", "-c", str(SRC),
          "-o", str(obj)])
    common = [link, "/DLL", "/NOENTRY", "/NODEFAULTLIB", "/MACHINE:X64",
              "/INCREMENTAL:NO", "/OPT:REF", "/OPT:ICF", "/Brepro"]
    ref = out / "windows_reference.dll"
    target = out / "windows_target.dll"
    call([*common, "/OUT:" + str(ref),
          "/EXPORT:re_lib_mix", "/EXPORT:re_lib_crc",
          "/EXPORT:re_lib_scramble", "/EXPORT:re_lib_unrelated", str(obj)])
    call([*common, "/OUT:" + str(target), str(obj)])
    results = {}
    for filename, expect in [(ref, EXPECTED_REFERENCE), (target, EXPECTED_TARGET)]:
        kind = identity(filename)
        observed = exports(call([dump, "-p", str(filename)]))
        if observed != expect:
            raise ValueError(f"{filename.name} exports {observed!r}, wanted {expect!r}")
        results[filename.name] = {"format": kind, "sha256": sha(filename),
                                  "size": filename.stat().st_size,
                                  "exports": sorted(observed)}
    if b"re_lib_" in target.read_bytes():
        raise ValueError("helper names leaked into target bytes")
    if results[ref.name]["sha256"] == results[target.name]["sha256"]:
        raise ValueError("reference and target identical")
    manifest = {"schema_version": 1, "status": "COMPILED_ONLY_NO_FID_MATCH_YET",
                "source_sha256": sha(SRC), "coff_sha256": sha(obj),
                "clang": call([clang, "--version"]).splitlines()[0],
                "lld_link": call([link, "--version"]).strip(),
                "files": results,
                "controls": ["target exports dispatcher only",
                             "reference exports 4 named helpers including decoy",
                             "no PE runtime execution"]}
    (out / "build-receipt.json").write_text(json.dumps(manifest, indent=2,
                                                   sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output:
        build(args.output)
    else:
        with tempfile.TemporaryDirectory(prefix="re-windows-fid-") as d:
            build(Path(d))


if __name__ == "__main__":
    main()
