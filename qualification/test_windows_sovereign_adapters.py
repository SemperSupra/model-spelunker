#!/usr/bin/env python3
"""Contract tests for Windows sovereign actor adapters: Aider, Vibe, OpenCode, Qwen Code."""

from __future__ import annotations

import json
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
    for adapter in ("aider_cli.py", "vibe_cli.py", "opencode_cli.py", "qwen_cli.py", "pi_cli.py"):
        res = run_adapter(adapter, "", os.environ.copy())
        assert res.returncode == 2, f"{adapter} expected 2 on empty instruction, got {res.returncode}"
        assert "missing task instruction on stdin" in res.stderr


def test_forbidden_credentials() -> None:
    for adapter in ("aider_cli.py", "vibe_cli.py", "opencode_cli.py", "qwen_cli.py", "pi_cli.py"):
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


def test_provider_select_negative_cases() -> None:
    """PROVIDER-SELECT: Missing active provider or missing config stops execution before invoking CLI."""
    env_clean = dict(os.environ)
    for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        env_clean.pop(k, None)

    with tempfile.TemporaryDirectory() as td:
        fake_bin = Path(td) / "fake.exe"
        fake_bin.write_text("", encoding="utf-8")

        # 1. Pi missing config dir
        env = dict(env_clean)
        env["PI_NODE_BIN"] = str(fake_bin)
        env["PI_CLI_JS"] = str(fake_bin)
        env["PI_CODING_AGENT_DIR"] = str(Path(td) / "nonexistent_pi_dir")
        env["PI_MOCK_DRY_RUN"] = "1"
        res = run_adapter("pi_cli.py", "Fix bug", env)
        assert res.returncode == 2
        assert "fail-closed: missing pi config directory" in res.stderr

        # 2. Pi models.json missing active provider
        pi_dir = Path(td) / "pi_cfg"
        pi_dir.mkdir()
        (pi_dir / "models.json").write_text(json.dumps({"providers": {}}), encoding="utf-8")
        env["PI_CODING_AGENT_DIR"] = str(pi_dir)
        env["PI_PROVIDER"] = "nonexistent_provider"
        res = run_adapter("pi_cli.py", "Fix bug", env)
        assert res.returncode == 2
        assert "fail-closed: active provider 'nonexistent_provider' not declared" in res.stderr

        # 3. OpenCode missing config file
        env = dict(env_clean)
        env["OPENCODE_CONFIG"] = str(Path(td) / "nonexistent_opencode.json")
        env["OPENCODE_BIN"] = str(fake_bin)
        env["OPENCODE_MOCK_DRY_RUN"] = "1"
        res = run_adapter("opencode_cli.py", "Fix bug", env)
        assert res.returncode == 2
        assert "fail-closed: missing opencode config file" in res.stderr

        # 4. OpenCode missing active provider
        opencode_cfg = Path(td) / "opencode.json"
        opencode_cfg.write_text(json.dumps({"providers": {}}), encoding="utf-8")
        env["OPENCODE_CONFIG"] = str(opencode_cfg)
        env["OPENCODE_MODEL"] = "missing_prov/model"
        res = run_adapter("opencode_cli.py", "Fix bug", env)
        assert res.returncode == 2
        assert "fail-closed: active provider 'missing_prov' not declared" in res.stderr

        # 5. Vibe missing config.toml
        env = dict(env_clean)
        env["VIBE_HOME"] = str(Path(td) / "nonexistent_vibe_home")
        env["VIBE_BIN"] = str(fake_bin)
        env["VIBE_MOCK_DRY_RUN"] = "1"
        res = run_adapter("vibe_cli.py", "Fix bug", env)
        assert res.returncode == 2
        assert "fail-closed: missing vibe config.toml" in res.stderr

        # 6. Vibe missing api_base for provider
        vibe_dir = Path(td) / "vibe_cfg"
        vibe_dir.mkdir()
        (vibe_dir / "config.toml").write_text('active_model = "test_model"\n[[models]]\nname = "test_model"\nprovider = "p"\n[[providers]]\nname = "p"\n', encoding="utf-8")
        env["VIBE_HOME"] = str(vibe_dir)
        res = run_adapter("vibe_cli.py", "Fix bug", env)
        assert res.returncode == 2
        assert "fail-closed: missing api_base for provider" in res.stderr

    print("PASS: PROVIDER-SELECT Missing config or provider stops execution before CLI launch")


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
        config_toml = Path(temp) / "config.toml"
        config_toml.write_text(
            'active_model = "bigmac"\n'
            '[[models]]\nname = "bigmac"\nprovider = "bigmac"\n'
            '[[providers]]\nname = "bigmac"\napi_base = "http://192.168.178.105:8080/v1"\n',
            encoding="utf-8",
        )
        env = dict(os.environ)
        for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(k, None)
        env.update({
            "VIBE_BIN": str(fake_bin),
            "VIBE_HOME": str(temp),
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
        cfg_file = Path(temp) / "opencode.json"
        cfg_file.write_text(
            json.dumps({"providers": {"bigmac": {"baseURL": "http://192.168.178.105:8080/v1"}}}),
            encoding="utf-8",
        )
        env = dict(os.environ)
        for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(k, None)
        env.update({
            "OPENCODE_BIN": str(fake_bin),
            "OPENCODE_CONFIG": str(cfg_file),
            "OPENCODE_MOCK_DRY_RUN": "1",
            "OPENCODE_MODEL": "bigmac/qwen3-coder-30b",
        })
        res = run_adapter("opencode_cli.py", "Fix the bug", env)
        assert res.returncode == 0, f"OpenCode dry-run failed: {res.stderr}"
        out = res.stdout
        assert "run Fix the bug" in out
        assert "--model bigmac/qwen3-coder-30b" in out
        assert "--auto" in out
        assert "--format json" in out


def test_pi_dry_run() -> None:
    with tempfile.TemporaryDirectory() as temp:
        fake_node = Path(temp) / "node.exe"
        fake_node.write_text("", encoding="utf-8")
        fake_cli = Path(temp) / "cli.js"
        fake_cli.write_text("", encoding="utf-8")
        models_json = Path(temp) / "models.json"
        models_json.write_text(
            json.dumps({"providers": {"bigmac": {"baseUrl": "http://192.168.178.105:8080/v1"}}}),
            encoding="utf-8",
        )
        env = dict(os.environ)
        for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(k, None)
        env.update({
            "PI_NODE_BIN": str(fake_node),
            "PI_CLI_JS": str(fake_cli),
            "PI_CODING_AGENT_DIR": str(temp),
            "PI_MOCK_DRY_RUN": "1",
            "PI_PROVIDER": "bigmac",
            "MODEL_SPELUNKER_MODEL": "qwen3-coder-30b",
        })
        res = run_adapter("pi_cli.py", "Fix the bug", env)
        assert res.returncode == 0, f"Pi dry-run failed: {res.stderr}"
        out = res.stdout
        assert "'-p', 'Fix the bug'" in out
        assert "'--provider', 'bigmac'" in out
        assert "'--model', 'qwen3-coder-30b'" in out


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
    test_provider_select_negative_cases()
    test_aider_dry_run()
    test_vibe_dry_run()
    test_opencode_dry_run()
    test_pi_dry_run()
    test_qwen_dry_run()
    print("PASS Windows sovereign actor adapter contract tests (Aider, Vibe, OpenCode, Pi, Qwen Code, PROVIDER-SELECT)")
