#!/usr/bin/env python3
"""Thin adapter from the harness-neutral task contract to projected Goose CLI."""

from __future__ import annotations

import ipaddress
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def is_private_or_local_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
            return True
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


def main() -> int:
    instruction = sys.stdin.read().strip()
    if not instruction:
        print("missing task instruction on stdin", file=sys.stderr)
        return 2

    goose_bin = os.environ.get("GOOSE_BIN")
    model = os.environ.get("GOOSE_MODEL") or os.environ.get("MODEL_SPELUNKER_MODEL", "qwen3:1.7b")
    if not goose_bin:
        print("GOOSE_BIN is required", file=sys.stderr)
        return 2
    if not Path(goose_bin).is_file():
        print(f"GOOSE_BIN not found: {goose_bin}", file=sys.stderr)
        return 2

    provider = os.environ.get("GOOSE_PROVIDER", "ollama")
    env = dict(os.environ)

    forbidden_cloud = (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    )
    present_cloud = [name for name in forbidden_cloud if os.environ.get(name)]
    if present_cloud:
        print(
            "cloud credentials forbidden in sovereign Goose run: "
            + ", ".join(present_cloud),
            file=sys.stderr,
        )
        return 2

    if provider == "ollama":
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
        if "GOOSE_OLLAMA_HOST" in env:
            env["OLLAMA_HOST"] = env["GOOSE_OLLAMA_HOST"]
    elif provider == "openai":
        base_url = env.get("GOOSE_OPENAI_BASE_URL") or env.get("OPENAI_BASE_URL") or ""
        if not base_url:
            print("OPENAI_BASE_URL or GOOSE_OPENAI_BASE_URL required for openai provider", file=sys.stderr)
            return 2
        if not is_private_or_local_url(base_url):
            print(f"fail-closed: OPENAI_BASE_URL must target a local/private network: {base_url}", file=sys.stderr)
            return 2
        env["OPENAI_BASE_URL"] = base_url
        api_key = env.get("GOOSE_OPENAI_API_KEY") or env.get("OPENAI_API_KEY") or ""
        if api_key:
            env["OPENAI_API_KEY"] = api_key
    else:
        print(f"unsupported sovereign goose provider: {provider}", file=sys.stderr)
        return 2

    env.update(
        {
            "GOOSE_MODE": "auto",
            "GOOSE_THINKING_EFFORT": "off",
            "GOOSE_TELEMETRY_OFF": "true",
            "GOOSE_TELEMETRY_ENABLED": "false",
            "GOOSE_RANDOM_THINKING_MESSAGES": "false",
            "CONFIGURE": "false",
            "XDG_CONFIG_HOME": env.get("GOOSE_XDG_CONFIG_HOME", str(Path.home() / ".config" / "goose")),
            "XDG_DATA_HOME": env.get("GOOSE_XDG_DATA_HOME", str(Path.home() / ".local" / "share" / "goose")),
        }
    )

    try:
        max_turns = int(os.environ.get("MODEL_SPELUNKER_MAX_ITERATIONS", "4"))
    except ValueError:
        print("MODEL_SPELUNKER_MAX_ITERATIONS must be an integer", file=sys.stderr)
        return 2
    if not 1 <= max_turns <= 24:
        print("MODEL_SPELUNKER_MAX_ITERATIONS must be between 1 and 24", file=sys.stderr)
        return 2

    command = [
        goose_bin,
        "run",
        "--text",
        instruction,
        "--provider",
        provider,
        "--model",
        model,
        "--no-session",
        "--no-profile",
        "--with-builtin",
        "developer",
        "--max-turns",
        str(max_turns),
        "--max-tool-repetitions",
        "2",
        "--output-format",
        "stream-json",
        "--stats",
    ]
    if os.name == "posix":
        # Replace the thin adapter process with Goose itself on POSIX.
        os.execvpe(command[0], command, env)
        raise AssertionError("os.execvpe returned unexpectedly")
    # On Windows, exec* does not replace the process image. Run the child
    # synchronously forwarding exit code. Child inherits stdout/stderr
    # descriptors so streaming is preserved directly to the temporary files.
    completed = subprocess.run(command, env=env, stdin=subprocess.DEVNULL)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
