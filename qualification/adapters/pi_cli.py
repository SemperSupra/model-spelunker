#!/usr/bin/env python3
"""Thin adapter from harness-neutral task contract to Pi coding agent."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def resolve_node_and_cli() -> tuple[str, str]:
    default_node = r"C:\Users\Mark\.local\sovereign-actors\tools\node\node.exe"
    default_cli = r"C:\Users\Mark\.local\sovereign-actors\npm\node_modules\@earendil-works\pi-coding-agent\dist\bundle\cli.js"

    node_bin = os.environ.get("PI_NODE_BIN") or (default_node if Path(default_node).is_file() else shutil.which("node"))
    cli_js = os.environ.get("PI_CLI_JS") or (default_cli if Path(default_cli).is_file() else "")

    if not node_bin or not Path(node_bin).is_file():
        raise FileNotFoundError(f"node executable not found: {node_bin}")
    if not cli_js or not Path(cli_js).is_file():
        raise FileNotFoundError(f"pi cli.js not found: {cli_js}")

    return str(Path(node_bin).resolve()), str(Path(cli_js).resolve())


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
            "cloud credentials forbidden in sovereign Pi run: "
            + ", ".join(present),
            file=sys.stderr,
        )
        return 2

    try:
        node_bin, cli_js = resolve_node_and_cli()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    provider = os.environ.get("PI_PROVIDER", "bigmac")
    model = os.environ.get("MODEL_SPELUNKER_MODEL", "qwen3-coder-30b")
    default_cfg = r"C:\Users\Mark\.local\sovereign-actors\config\pi"
    cfg_dir = os.environ.get("PI_CODING_AGENT_DIR") or (default_cfg if Path(default_cfg).is_dir() else "")

    env = dict(os.environ)
    env.update(
        {
            "PI_OFFLINE": "1",
            "PI_TELEMETRY": "0",
            "PI_SKIP_VERSION_CHECK": "1",
        }
    )
    if cfg_dir:
        env["PI_CODING_AGENT_DIR"] = cfg_dir

    tools = os.environ.get("PI_TOOLS", "read,write,edit")

    command = [
        node_bin,
        cli_js,
        "-p",
        instruction,
        "--provider",
        provider,
        "--model",
        model,
        "--no-session",
        "--no-extensions",
        "--no-mcp",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--offline",
        "--tools",
        tools,
    ]

    if os.environ.get("PI_MOCK_DRY_RUN") == "1":
        print(f"PI_COMMAND={command}")
        return 0

    # Execute Pi. Use stdin=DEVNULL so Node does not hang awaiting trailing console input
    completed = subprocess.run(command, env=env, stdin=subprocess.DEVNULL)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
