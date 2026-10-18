#!/usr/bin/env python3
"""Thin adapter from harness-neutral task contract to Mistral Vibe agent."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from qualification.endpoint_policy import (
        validate_sovereign_endpoint,
        resolve_sovereign_api_key,
        FORBIDDEN_CLOUD_CREDENTIALS,
    )
except ImportError:
    from endpoint_policy import (
        validate_sovereign_endpoint,
        resolve_sovereign_api_key,
        FORBIDDEN_CLOUD_CREDENTIALS,
    )


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

    present = [name for name in FORBIDDEN_CLOUD_CREDENTIALS if os.environ.get(name)]
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
    endpoint_url = os.environ.get("VIBE_OPENAI_BASE_URL") or "http://192.168.178.105:8080/v1"
    try:
        validate_sovereign_endpoint(endpoint_url)
    except ValueError as exc:
        print(f"fail-closed: target model base URL must be local/private: {exc}", file=sys.stderr)
        return 2

    bigmac_key = resolve_sovereign_api_key(("BIGMAC_API_KEY",))

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
