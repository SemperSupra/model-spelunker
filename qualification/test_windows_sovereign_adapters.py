#!/usr/bin/env python3
"""Contract tests for Windows sovereign actor adapters: Aider, Vibe, OpenCode, Qwen Code."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS_DIR = ROOT / "qualification" / "adapters"


def run_adapter(adapter_name: str, stdin_text: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    adapter_path = ADAPTERS_DIR / adapter_name
    return subprocess.run(
        [sys.executable, str(adapter_path)],
        input=stdin_text,
        text=True,
        capture_output=True,
        env=env,
    )


def test_missing_instructions() -> None:
    for adapter in ("aider_cli.py", "vibe_cli.py", "opencode_cli.py", "qwen_cli.py"):
        res = run_adapter(adapter, "", os.environ.copy())
        assert res.returncode == 2, f"{adapter} expected 2 on empty instruction, got {res.returncode}"
        assert "missing task instruction on stdin" in res.stderr


def test_forbidden_credentials() -> None:
    for adapter in ("aider_cli.py", "vibe_cli.py", "opencode_cli.py", "qwen_cli.py"):
        env = dict(os.environ)
        env["OPENROUTER_API_KEY"] = "sk-fake-openrouter"
        res = run_adapter(adapter, "Do something", env)
        assert res.returncode == 2, f"{adapter} expected 2 on cloud credentials, got {res.returncode}"
        assert "cloud credentials forbidden in sovereign" in res.stderr


def test_private_route_enforcement() -> None:
    for adapter, env_var in (("aider_cli.py", "AIDER_OPENAI_API_BASE"), ("qwen_cli.py", "QWEN_OPENAI_BASE_URL")):
        with tempfile.TemporaryDirectory() as temp:
            fake_bin = Path(temp) / "fake.exe"
            fake_bin.write_text("", encoding="utf-8")
            env = dict(os.environ)
            for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
                env.pop(k, None)
            env[env_var] = "https://api.openai.com/v1"
            if adapter == "aider_cli.py":
                env["AIDER_BIN"] = str(fake_bin)
            else:
                env["QWEN_BIN"] = str(fake_bin)
            res = run_adapter(adapter, "Task instruction", env)
            assert res.returncode == 2, f"{adapter} expected 2 on public URL, got {res.returncode}"
            assert "fail-closed: target model base URL must be local/private" in res.stderr


def test_aider_dry_run() -> None:
    with tempfile.TemporaryDirectory() as temp:
        fake_bin = Path(temp) / "fake_aider.exe"
        fake_bin.write_text("", encoding="utf-8")
        env = dict(os.environ)
        for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(k, None)
        env.update({
            "AIDER_BIN": str(fake_bin),
            "AIDER_MOCK_DRY_RUN": "1",
            "AIDER_OPENAI_API_BASE": "http://192.168.178.105:8080/v1",
            "AIDER_MODEL": "qwen3-coder-30b",
        })
        res = run_adapter("aider_cli.py", "Fix the bug", env)
        assert res.returncode == 0, f"Aider dry-run failed: {res.stderr}"
        out = res.stdout
        assert "--openai-api-base http://192.168.178.105:8080/v1" in out
        assert "--model openai/qwen3-coder-30b" in out
        assert "--no-git" in out
        assert "--yes-always" in out
        assert "--no-auto-commits" in out


def test_vibe_dry_run() -> None:
    with tempfile.TemporaryDirectory() as temp:
        fake_bin = Path(temp) / "fake_vibe.exe"
        fake_bin.write_text("", encoding="utf-8")
        env = dict(os.environ)
        for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(k, None)
        env.update({
            "VIBE_BIN": str(fake_bin),
            "VIBE_MOCK_DRY_RUN": "1",
        })
        res = run_adapter("vibe_cli.py", "Fix the bug", env)
        assert res.returncode == 0, f"Vibe dry-run failed: {res.stderr}"
        out = res.stdout
        assert "-p Fix the bug" in out
        assert "--trust" in out
        assert "--auto-approve" in out


def test_opencode_dry_run() -> None:
    with tempfile.TemporaryDirectory() as temp:
        fake_bin = Path(temp) / "fake_opencode.cmd"
        fake_bin.write_text("", encoding="utf-8")
        env = dict(os.environ)
        for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(k, None)
        env.update({
            "OPENCODE_BIN": str(fake_bin),
            "OPENCODE_MOCK_DRY_RUN": "1",
            "OPENCODE_MODEL": "qwen3-coder-30b",
        })
        res = run_adapter("opencode_cli.py", "Fix the bug", env)
        assert res.returncode == 0, f"OpenCode dry-run failed: {res.stderr}"
        out = res.stdout
        assert "run Fix the bug" in out
        assert "--model bigmac/qwen3-coder-30b" in out
        assert "--auto" in out
        assert "--format json" in out


def test_qwen_dry_run() -> None:
    with tempfile.TemporaryDirectory() as temp:
        fake_bin = Path(temp) / "fake_qwen.cmd"
        fake_bin.write_text("", encoding="utf-8")
        env = dict(os.environ)
        for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(k, None)
        env.update({
            "QWEN_BIN": str(fake_bin),
            "QWEN_MOCK_DRY_RUN": "1",
            "QWEN_OPENAI_BASE_URL": "http://192.168.178.105:8080/v1",
            "QWEN_MODEL": "qwen3-coder-30b",
        })
        res = run_adapter("qwen_cli.py", "Fix the bug", env)
        assert res.returncode == 0, f"Qwen dry-run failed: {res.stderr}"
        out = res.stdout
        assert "-p Fix the bug" in out
        assert "--approval-mode yolo" in out
        assert "--auth-type openai" in out
        assert "--openai-base-url http://192.168.178.105:8080/v1" in out
        assert "-m qwen3-coder-30b" in out


if __name__ == "__main__":
    test_missing_instructions()
    test_forbidden_credentials()
    test_private_route_enforcement()
    test_aider_dry_run()
    test_vibe_dry_run()
    test_opencode_dry_run()
    test_qwen_dry_run()
    print("PASS Windows sovereign actor adapter contract tests (Aider, Vibe, OpenCode, Qwen Code)")
