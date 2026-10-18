#!/usr/bin/env python3
"""Contract test for Pi adapter: offline validation, credential isolation, and command formation."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "qualification" / "adapters" / "pi_cli.py"


def test_pi_missing_instruction() -> None:
    res = subprocess.run(
        [sys.executable, str(ADAPTER)],
        input="",
        text=True,
        capture_output=True,
    )
    assert res.returncode == 2, f"Expected 2 on missing instruction, got {res.returncode}"
    assert "missing task instruction on stdin" in res.stderr


def test_pi_forbidden_credentials() -> None:
    env = dict(os.environ)
    env["OPENROUTER_API_KEY"] = "sk-test-fake"
    res = subprocess.run(
        [sys.executable, str(ADAPTER)],
        input="Do something",
        text=True,
        capture_output=True,
        env=env,
    )
    assert res.returncode == 2, f"Expected 2 on cloud credentials, got {res.returncode}"
    assert "cloud credentials forbidden in sovereign Pi run" in res.stderr


def test_pi_dry_run_command_formation() -> None:
    with tempfile.TemporaryDirectory() as temp:
        fake_node = Path(temp) / "node.exe"
        fake_node.write_text("", encoding="utf-8")
        fake_cli = Path(temp) / "cli.js"
        fake_cli.write_text("", encoding="utf-8")

        env = dict(os.environ)
        for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(k, None)

        env.update({
            "PI_NODE_BIN": str(fake_node),
            "PI_CLI_JS": str(fake_cli),
            "PI_PROVIDER": "bigmac",
            "MODEL_SPELUNKER_MODEL": "qwen3-coder-30b",
            "PI_MOCK_DRY_RUN": "1",
        })

        res = subprocess.run(
            [sys.executable, str(ADAPTER)],
            input="Replace value.txt",
            text=True,
            capture_output=True,
            env=env,
        )
        assert res.returncode == 0, f"Expected 0 on dry run, got {res.returncode}: {res.stderr}"
        assert "--provider" in res.stdout
        assert "bigmac" in res.stdout
        assert "--model" in res.stdout
        assert "qwen3-coder-30b" in res.stdout
        assert "--offline" in res.stdout
        assert "--no-session" in res.stdout
        assert "--tools" in res.stdout
        assert "read,write,edit" in res.stdout


if __name__ == "__main__":
    test_pi_missing_instruction()
    test_pi_forbidden_credentials()
    test_pi_dry_run_command_formation()
    print("PASS Pi adapter contract tests (rejection, credential isolation, dry-run arguments)")
