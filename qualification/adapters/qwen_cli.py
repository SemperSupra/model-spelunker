#!/usr/bin/env python3
"""Thin adapter from harness-neutral task contract to Qwen Code agent."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path


def is_private_or_local_url(url_string: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url_string)
        host = parsed.hostname or ""
        if host in {"127.0.0.1", "localhost", "::1"}:
            return True
        parts = [int(p) for p in host.split(".")]
        if len(parts) == 4:
            if parts[0] == 10:
                return True
            if parts[0] == 172 and 16 <= parts[1] <= 31:
                return True
            if parts[0] == 192 and parts[1] == 168:
                return True
        return False
    except Exception:
        return False


def resolve_qwen_bin() -> str:
    default_cmd = r"C:\Users\Mark\.local\sovereign-actors\npm\qwen.cmd"
    bin_path = os.environ.get("QWEN_BIN") or (default_cmd if Path(default_cmd).is_file() else shutil.which("qwen"))
    if not bin_path or not Path(bin_path).is_file():
        raise FileNotFoundError(f"qwen executable not found: {bin_path}")
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
    if not is_private_or_local_url(base_url):
        print(f"fail-closed: target model base URL must be local/private: {base_url}", file=sys.stderr)
        return 2

    api_key = (
        os.environ.get("QWEN_OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("BIGMAC_API_KEY")
    )
    if not api_key:
        endpoint_config = Path.home() / ".local" / "sovereign-actors" / "config" / "endpoint.json"
        if endpoint_config.is_file():
            try:
                import json
                data = json.loads(endpoint_config.read_text(encoding="utf-8"))
                api_key = data.get("endpoints", {}).get("bigmac", {}).get("api_key")
            except Exception:
                pass
    if not api_key:
        api_key = "local-sovereign-dummy-key"

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
        "--openai-api-key",
        api_key,
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
