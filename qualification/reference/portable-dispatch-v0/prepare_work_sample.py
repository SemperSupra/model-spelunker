#!/usr/bin/env python3
"""Prepare stripped ELF object for a controlled semantic reconstruction work sample.

Trusted side only; do not mount this directory into an actor workcell.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK = ROOT.parents[1] / "tasks" / "portable-dispatch-semantics-v0"


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--destination", type=Path, required=True)
    ap.add_argument("--cc", default="clang")
    ap.add_argument("--objdump", default="llvm-objdump")
    ap.add_argument("--strip", default="strip")
    args = ap.parse_args()
    root = args.destination.resolve()
    if root == TASK.resolve() or root == ROOT.resolve() or root == Path.cwd().resolve():
        raise ValueError("refusing source or cwd overwrite")
    root.mkdir(parents=True, exist_ok=True)
    dest = root / "fixture"
    dest.mkdir(exist_ok=True)
    for name in ("task.json", "verify.py"):
        shutil.copyfile(TASK / name, root / name)
    source = ROOT / "dispatcher.c"
    version_script = root / "exports.map"
    version_script.write_text("{ global: command_dispatch; local: *; };\n", encoding="utf-8")
    target = dest / "target.bin"
    cmd = [args.cc, "-O1", "-shared", "-fPIC", "-fno-stack-protector", "-fno-ident", "-Wl,--build-id=none",
           f"-Wl,--version-script={version_script}", str(source), "-o", str(target)]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=90)
    subprocess.run([args.strip, "--strip-all", str(target)], check=True, capture_output=True, text=True, timeout=30)
    objdump = shutil.which(args.objdump) or shutil.which("objdump")
    if not objdump:
        raise RuntimeError("no objdump compatible disassembler on execution host")
    options = ["--disassemble"]
    if "llvm-objdump" in Path(objdump).name:
        options.append("--print-imm-hex")
    # Absolute target paths leak disposable workdir names into the disassembly header.
    # Use a stable relative operand and cwd, so identical bytes + tool versions match.
    disasm = subprocess.run([objdump, *options, target.name], cwd=dest, check=True,
                            capture_output=True, text=True, timeout=30).stdout
    if not disasm.strip():
        raise RuntimeError("disassembly empty")
    (dest / "disassembly.txt").write_text(disasm, encoding="utf-8")
    version_script.unlink()
    def tool_version(executable: str) -> str:
        proc = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10, check=True)
        return proc.stdout.splitlines()[0] if proc.stdout else "UNKNOWN"

    manifest = {"schema_version": 1, "source_sha256": digest(source),
                "tool_versions": {"compiler": tool_version(args.cc),
                                  "strip": tool_version(args.strip),
                                  "objdump": tool_version(objdump)},
                "sha256": {name: digest(dest / name) for name in ("target.bin", "disassembly.txt")},
                "build_command_profile": "source-known-clang-O1-stripped-shared-ELF",
                "status": "UNQUALIFIED_ACTOR_TASK"}
    (root / "oracle_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
