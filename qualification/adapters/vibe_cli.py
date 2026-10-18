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
    config_file = Path(vibe_home) / "config.toml"
    if not config_file.is_file():
        print(f"fail-closed: missing vibe config.toml in {vibe_home}", file=sys.stderr)
        return 2

    try:
        import tomllib
        with open(config_file, "rb") as f:
            cfg_data = tomllib.load(f)
        active_model_name = cfg_data.get("active_model", "bigmac")
        models = cfg_data.get("models", [])
        provider_name = None
        for m in models:
            if m.get("name") == active_model_name or m.get("alias") == active_model_name:
                provider_name = m.get("provider", m.get("name"))
                break
        if not provider_name:
            provider_name = active_model_name

        providers = cfg_data.get("providers", [])
        active_api_base = None
        for p in providers:
            if p.get("name") == provider_name:
                active_api_base = p.get("api_base")
                break
        if not active_api_base:
            print(f"fail-closed: missing api_base for provider '{provider_name}' in {config_file}", file=sys.stderr)
            return 2
        validate_sovereign_endpoint(active_api_base)
    except Exception as exc:
        print(f"fail-closed: cannot validate sovereign route in vibe config.toml: {exc}", file=sys.stderr)
        return 2

    endpoint_url = active_api_base

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
