#!/usr/bin/env python3
"""Thin adapter from harness-neutral task contract to Qwen Code CLI."""

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


def resolve_qwen_bin() -> str:
    candidates = [
        os.environ.get("QWEN_BIN"),
        r"C:\Users\Mark\.local\wow-actors\bin\qwen.cmd",
        r"C:\Users\Mark\.local\sovereign-actors\tools\node\node_modules\@qwen-code\cli\bin\qwen.js",
        shutil.which("qwen.cmd"),
        shutil.which("qwen"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return str(Path(c).resolve())
    raise FileNotFoundError("qwen executable not found")


def main() -> int:
    instruction = sys.stdin.read().strip()
    if not instruction:
        print("missing task instruction on stdin", file=sys.stderr)
        return 2

    present = [name for name in FORBIDDEN_CLOUD_CREDENTIALS if os.environ.get(name)]
    if present:
        print(
            "cloud credentials forbidden in sovereign Qwen Code run: "
            + ", ".join(present),
            file=sys.stderr,
        )
        return 2

    try:
        qwen_bin = resolve_qwen_bin()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    base_url = (
        os.environ.get("QWEN_OPENAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "http://192.168.178.105:8080/v1"
    )
    try:
        validate_sovereign_endpoint(base_url)
    except ValueError as exc:
        print(f"fail-closed: target model base URL must be local/private: {exc}", file=sys.stderr)
        return 2

    api_key = resolve_sovereign_api_key(("QWEN_OPENAI_API_KEY",))

    model = (
        os.environ.get("QWEN_MODEL")
        or os.environ.get("MODEL_SPELUNKER_MODEL")
        or "qwen3-coder-30b"
    )

    node_dir = r"C:\Users\Mark\.local\sovereign-actors\tools\node"
    env = dict(os.environ)
    if Path(node_dir).is_dir():
        env["PATH"] = f"{node_dir};" + env.get("PATH", "")

    settings_path = r"C:\Users\Mark\.local\sovereign-actors\config\qwen-home\settings.json"
    if Path(settings_path).is_file():
        env["QWEN_CODE_SYSTEM_SETTINGS_PATH"] = settings_path

    runtime_dir = r"C:\Users\Mark\.local\sovereign-actors\state\qwen"
    if Path(runtime_dir).is_dir():
        env["QWEN_RUNTIME_DIR"] = runtime_dir

    env["QWEN_USAGE_STATISTICS_ENABLED"] = "0"
    env["QWEN_TELEMETRY_ENABLED"] = "0"
    env["QWEN_CODE_SUPPRESS_YOLO_WARNING"] = "1"
    env["OPENAI_API_KEY"] = api_key

    # Omit API key from argv so argv and process logs never expose credentials
    command = [
        qwen_bin,
        "-p",
        instruction,
        "--approval-mode",
        "yolo",
        "--auth-type",
        "openai",
        "--openai-base-url",
        base_url,
        "-m",
        model,
        "--output-format",
        "json",
    ]

    if os.environ.get("QWEN_MOCK_DRY_RUN") == "1":
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
