#!/usr/bin/env python3
"""Thin adapter from harness-neutral task contract to OpenCode agent."""

from __future__ import annotations

import json
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
        FORBIDDEN_CLOUD_CREDENTIALS,
    )
except ImportError:
    from endpoint_policy import (
        validate_sovereign_endpoint,
        FORBIDDEN_CLOUD_CREDENTIALS,
    )


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

    present = [name for name in FORBIDDEN_CLOUD_CREDENTIALS if os.environ.get(name)]
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

    if "OPENCODE_CONFIG" in os.environ:
        cfg_file = os.environ["OPENCODE_CONFIG"]
        if not Path(cfg_file).is_file():
            print(f"fail-closed: missing opencode config file: {cfg_file}", file=sys.stderr)
            return 2
    else:
        default_cfg = r"C:\Users\Mark\.local\sovereign-actors\config\opencode.json"
        alt_cfg = str(Path.home() / ".config" / "opencode" / "opencode.json")
        if Path(default_cfg).is_file():
            cfg_file = default_cfg
        elif Path(alt_cfg).is_file():
            cfg_file = alt_cfg
        else:
            print(f"fail-closed: missing opencode config file (checked {default_cfg} and {alt_cfg})", file=sys.stderr)
            return 2

    model = os.environ.get("OPENCODE_MODEL") or os.environ.get("MODEL_SPELUNKER_MODEL") or "bigmac/qwen3-coder-30b"
    if "/" not in model:
        model = f"bigmac/{model}"
    active_provider = model.split("/")[0]

    # Validate exact provider endpoint in opencode config for the active provider
    try:
        cfg_data = json.loads(Path(cfg_file).read_text(encoding="utf-8"))
        providers = cfg_data.get("providers", {})
        if active_provider not in providers:
            print(f"fail-closed: active provider '{active_provider}' not declared in {cfg_file}", file=sys.stderr)
            return 2
        active_cfg = providers[active_provider]
        base_url = active_cfg.get("baseURL") or active_cfg.get("baseUrl")
        if not base_url:
            print(f"fail-closed: missing baseURL for active provider '{active_provider}' in {cfg_file}", file=sys.stderr)
            return 2
        validate_sovereign_endpoint(base_url)
    except Exception as exc:
        print(f"fail-closed: invalid sovereign provider endpoint in opencode config: {exc}", file=sys.stderr)
        return 2

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
