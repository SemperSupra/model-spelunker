#!/usr/bin/env python3
"""Independent Windows native MSVC source-known PE/PDB/library build oracle."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

EXPECTED_REF = {"re_dispatch", "re_lib_mix", "re_lib_crc", "re_lib_scramble", "re_lib_unrelated"}
EXPECTED_TARGET = {"re_dispatch"}
ROW = re.compile(r"^\s*\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+(re_[A-Za-z0-9_]+)(?=\s|$)")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pe_identity(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 256 or data[:2] != b"MZ":
        raise ValueError(f"{path.name} missing DOS PE header")
    offset = struct.unpack_from("<I", data, 0x3c)[0]
    if offset > len(data) - 0x80 or data[offset:offset + 4] != b"PE\0\0":
        raise ValueError(f"{path.name} missing PE signature")
    machine = struct.unpack_from("<H", data, offset + 4)[0]
    magic = struct.unpack_from("<H", data, offset + 24)[0]
    if (machine, magic) != (0x8664, 0x20b):
        raise ValueError(f"{path.name} is not Windows x64 PE32+")
    return {"format": "PE32+ x64", "size": len(data), "sha256": sha(path)}


def exports(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {m.group(1) for line in lines if (m := ROW.match(line))}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    opts = p.parse_args()
    root = opts.output
    expected = {
        "reference_labeled.dll": EXPECTED_REF,
        "target_stripped.dll": EXPECTED_TARGET,
    }
    files: dict = {}
    for name, expected_symbols in expected.items():
        path = root / name
        meta = pe_identity(path)
        found = exports(root / ("reference-exports.txt" if name.startswith("reference") else "target-exports.txt"))
        if found != expected_symbols:
            raise ValueError(f"{name}: wrong exported symbols {sorted(found)}, expected {sorted(expected_symbols)}")
        files[name] = {**meta, "exports": sorted(found)}
    if b"re_lib_" in (root / "target_stripped.dll").read_bytes():
        raise ValueError("unintended helper names leaked to PE target")
    required = ("reference.obj", "reference_static.lib", "reference_labeled.pdb",
                "target_stripped.pdb", "reference-symbols.txt", "msvc-inventory.json")
    for name in required:
        if not (root / name).is_file() or (root / name).stat().st_size < 64:
            raise ValueError(f"missing or empty reference material {name}")
    objects = (root / "reference-symbols.txt").read_text(encoding="utf-8", errors="replace")
    for name in sorted(EXPECTED_REF):
        if name not in objects:
            raise ValueError(f"source-defined {name} absent from original COFF object symbols")
    inventory = json.loads((root / "msvc-inventory.json").read_text(encoding="utf-8-sig"))
    for k in ("vc_archives_x64", "ucrt_archives_x64", "windows_sdk_import_archives_x64"):
        if type(inventory[k]) is not int or inventory[k] < 1:
            raise ValueError(f"Visual Studio installed archive category absent: {k}")
    receipt = {
        "schema_version": 1,
        "status": "PASS_NATIVE_MSVC_WINDOWS_PRODUCER_NOT_FID_MATCH",
        "compiler_install": inventory["visual_studio_install"],
        "vc_toolchain": inventory["vc_tools_version"],
        "windows_sdk": inventory["windows_sdk_version"],
        "installed_archives": {k: inventory[k] for k in
                              ("vc_archives_x64", "ucrt_archives_x64", "windows_sdk_import_archives_x64")},
        "source_sha256": sha(Path(__file__).parent / "windows_reference.c"),
        "objects": {"coff_object_sha256": sha(root / "reference.obj"),
                    "code_bearing_lib_sha256": sha(root / "reference_static.lib")},
        "files": files,
        "negative_controls": ["target does not export library/helper names",
                              "reference COFF retains correct labels",
                              "target contains no helper-name strings",
                              "not a runnable app/PE not executed"],
    }
    (root / "windows-native-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
