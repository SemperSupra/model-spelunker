#!/usr/bin/env python3
"""Thin adapter from the harness-neutral task contract to projected Goose CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    instruction = sys.stdin.read().strip()
    if not instruction:
        print("missing task instruction on stdin", file=sys.stderr)
        return 2

    goose_bin = os.environ.get("GOOSE_BIN")
    model = os.environ.get("MODEL_SPELUNKER_MODEL", "qwen3:1.7b")
    if not goose_bin:
        print("GOOSE_BIN is required", file=sys.stderr)
        return 2
    if not Path(goose_bin).is_file():
        print(f"GOOSE_BIN not found: {goose_bin}", file=sys.stderr)
        return 2

    forbidden = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OLLAMA_API_KEY",
    )
    present = [name for name in forbidden if os.environ.get(name)]
    if present:
        print(
            "credential-free Goose crossover received model credentials: "
            + ", ".join(present),
            file=sys.stderr,
        )
        return 2

    env = dict(os.environ)
    env.update(
        {
            "GOOSE_MODE": "auto",
            "GOOSE_THINKING_EFFORT": "off",
            "GOOSE_TELEMETRY_OFF": "true",
            "GOOSE_TELEMETRY_ENABLED": "false",
            "GOOSE_RANDOM_THINKING_MESSAGES": "false",
            "CONFIGURE": "false",
            "OLLAMA_HOST": env["GOOSE_OLLAMA_HOST"],
            "XDG_CONFIG_HOME": env["GOOSE_XDG_CONFIG_HOME"],
            "XDG_DATA_HOME": env["GOOSE_XDG_DATA_HOME"],
        }
    )

    command = [
        goose_bin,
        "run",
        "--text",
        instruction,
        "--provider",
        "ollama",
        "--model",
        model,
        "--no-session",
        "--no-profile",
        "--with-builtin",
        "developer",
        "--max-turns",
        "4",
        "--max-tool-repetitions",
        "2",
        "--output-format",
        "stream-json",
        "--stats",
    ]
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
