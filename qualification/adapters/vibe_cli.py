#!/usr/bin/env python3
"""Thin adapter from harness-neutral task contract to Mistral Vibe agent."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def resolve_vibe_bin() -> str:
    default_bin = r"C:\Users\Mark\.local\bin\vibe.exe"
    bin_path = os.environ.get("VIBE_BIN") or (default_bin if Path(default_bin).is_file() else shutil.which("vibe"))
    if not bin_path or not Path(bin_path).is_file():
        raise FileNotFoundError(f"vibe executable not found: {bin_path}")
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
            "cloud credentials forbidden in sovereign Vibe run: "
            + ", ".join(present),
            file=sys.stderr,
        )
        return 2

    try:
        vibe_bin = resolve_vibe_bin()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    vibe_home = os.environ.get("VIBE_HOME") or r"C:\Users\Mark\.local\sovereign-actors\config\vibe"
    bigmac_key = os.environ.get("BIGMAC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not bigmac_key:
        endpoint_config = Path.home() / ".local" / "sovereign-actors" / "config" / "endpoint.json"
        if endpoint_config.is_file():
            try:
                import json
                data = json.loads(endpoint_config.read_text(encoding="utf-8"))
                bigmac_key = data.get("endpoints", {}).get("bigmac", {}).get("api_key")
            except Exception:
                pass
    if not bigmac_key:
        bigmac_key = "local-sovereign-dummy-key"

    env = dict(os.environ)
    env["VIBE_HOME"] = vibe_home
    env["BIGMAC_API_KEY"] = bigmac_key

    command = [
        vibe_bin,
        "-p",
        instruction,
        "--trust",
        "--auto-approve",
        "--output",
        "streaming",
    ]

    if os.environ.get("VIBE_MOCK_DRY_RUN") == "1":
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
