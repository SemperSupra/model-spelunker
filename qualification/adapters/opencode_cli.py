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

    cfg_file = os.environ.get("OPENCODE_CONFIG") or r"C:\Users\Mark\.local\sovereign-actors\config\opencode.json"
    if not Path(cfg_file).is_file():
        cfg_file = str(Path.home() / ".config" / "opencode" / "opencode.json")

    model = os.environ.get("OPENCODE_MODEL") or os.environ.get("MODEL_SPELUNKER_MODEL") or "bigmac/qwen3-coder-30b"
    if "/" not in model:
        model = f"bigmac/{model}"
    active_provider = model.split("/")[0]

    # Validate provider endpoint in opencode config for the active provider
    if Path(cfg_file).is_file():
        try:
            cfg_data = json.loads(Path(cfg_file).read_text(encoding="utf-8"))
            providers = cfg_data.get("providers", {})
            active_cfg = providers.get(active_provider)
            if active_cfg:
                base_url = active_cfg.get("baseURL") or active_cfg.get("baseUrl")
                if not base_url:
                    print(f"fail-closed: missing baseURL for active provider '{active_provider}' in {cfg_file}", file=sys.stderr)
                    return 2
                validate_sovereign_endpoint(base_url)
            else:
                for p_name, p_val in providers.items():
                    base_url = p_val.get("baseURL") or p_val.get("baseUrl")
                    if base_url:
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
