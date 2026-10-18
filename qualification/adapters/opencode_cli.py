#!/usr/bin/env python3
"""Thin adapter from harness-neutral task contract to OpenCode agent."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def resolve_opencode_bin() -> str:
    default_cmd = r"C:\Users\Mark\.local\sovereign-actors\npm\opencode.cmd"
    bin_path = os.environ.get("OPENCODE_BIN") or (default_cmd if Path(default_cmd).is_file() else shutil.which("opencode"))
    if not bin_path or not Path(bin_path).is_file():
        raise FileNotFoundError(f"opencode executable not found: {bin_path}")
    return str(Path(bin_path).resolve())


def main() -> int:
    instruction = sys.stdin.read().strip()
    if not instruction:
        print("missing task instruction on stdin", file=sys.stderr)
        return 2

    forbidden_cloud = (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    )
    present = [name for name in forbidden_cloud if os.environ.get(name)]
    if present:
        print(
            "cloud credentials forbidden in sovereign OpenCode run: "
            + ", ".join(present),
            file=sys.stderr,
        )
        return 2

    try:
        opencode_bin = resolve_opencode_bin()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    cfg_file = os.environ.get("OPENCODE_CONFIG") or r"C:\Users\Mark\.local\sovereign-actors\config\opencode.json"
    if not Path(cfg_file).is_file():
        cfg_file = str(Path.home() / ".config" / "opencode" / "opencode.json")

    model = os.environ.get("OPENCODE_MODEL") or os.environ.get("MODEL_SPELUNKER_MODEL") or "bigmac/qwen3-coder-30b"
    if "/" not in model:
        model = f"bigmac/{model}"

    env = dict(os.environ)
    env["OPENCODE_CONFIG"] = cfg_file
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env["OPENCODE_AUTO_SHARE"] = "false"

    command = [
        opencode_bin,
        "run",
        instruction,
        "--model",
        model,
        "--auto",
        "--format",
        "json",
    ]

    if os.environ.get("OPENCODE_MOCK_DRY_RUN") == "1":
        print(" ".join(command))
        return 0

    completed = subprocess.run(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
