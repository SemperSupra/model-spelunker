#!/usr/bin/env python3
"""Thin adapter from harness-neutral task contract to Aider coding agent."""

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


def resolve_aider_bin() -> str:
    default_bin = r"C:\Users\Mark\.local\bin\aider.exe"
    bin_path = os.environ.get("AIDER_BIN") or (default_bin if Path(default_bin).is_file() else shutil.which("aider"))
    if not bin_path or not Path(bin_path).is_file():
        raise FileNotFoundError(f"aider executable not found: {bin_path}")
    return str(Path(bin_path).resolve())


def main() -> int:
    instruction = sys.stdin.read().strip()
    if not instruction:
        print("missing task instruction on stdin", file=sys.stderr)
        return 2

    present = [name for name in FORBIDDEN_CLOUD_CREDENTIALS if os.environ.get(name)]
    if present:
        print(
            "cloud credentials forbidden in sovereign Aider run: "
            + ", ".join(present),
            file=sys.stderr,
        )
        return 2

    try:
        aider_bin = resolve_aider_bin()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    base_url = (
        os.environ.get("AIDER_OPENAI_API_BASE")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or "http://192.168.178.105:8080/v1"
    )
    try:
        validate_sovereign_endpoint(base_url)
    except ValueError as exc:
        print(f"fail-closed: target model base URL must be local/private: {exc}", file=sys.stderr)
        return 2

    api_key = resolve_sovereign_api_key(("AIDER_OPENAI_API_KEY",))

    model_name = (
        os.environ.get("AIDER_MODEL")
        or os.environ.get("MODEL_SPELUNKER_MODEL")
        or "qwen3-coder-30b"
    )
    if not model_name.startswith("openai/"):
        model_name = f"openai/{model_name}"

    edit_format = os.environ.get("AIDER_EDIT_FORMAT", "diff")

    # Resolve target files from task environment so Aider has file context in headless mode
    allowed_paths_raw = (
        os.environ.get("MODEL_SPELUNKER_ALLOWED_WRITE_PATHS")
        or os.environ.get("MODEL_SPELUNKER_WRITE_TARGET")
        or ""
    )
    target_files = [p.strip() for p in allowed_paths_raw.split(",") if p.strip()]

    # Omit API key from argv so argv and process logs never expose credentials
    command = [
        aider_bin,
        "--openai-api-base",
        base_url,
        "--model",
        model_name,
        "--edit-format",
        edit_format,
        "--no-git",
        "--yes-always",
        "--no-auto-commits",
        "--no-analytics",
        "--no-check-update",
        "--message",
        instruction,
    ]
    if target_files:
        command.extend(target_files)

    if os.environ.get("AIDER_MOCK_DRY_RUN") == "1":
        print(" ".join(command))
        return 0

    env = dict(os.environ)
    env["OPENAI_API_BASE"] = base_url
    env["OPENAI_API_KEY"] = api_key

    completed = subprocess.run(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
