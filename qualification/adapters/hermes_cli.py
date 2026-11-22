#!/usr/bin/env python3
"""Thin adapter from harness-neutral task contract to Hermes Agent."""

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


def resolve_hermes_bin() -> str:
    default_bin = r"C:\Users\Mark\AppData\Local\hermes\bin\hermes.exe"
    bin_path = os.environ.get("HERMES_BIN") or (default_bin if Path(default_bin).is_file() else shutil.which("hermes"))
    if not bin_path or not Path(bin_path).is_file():
        raise FileNotFoundError(f"hermes executable not found: {bin_path}")
    return str(Path(bin_path).resolve())


def sanitize_workspace_trailing_whitespace(root: Path | None = None) -> None:
    """Normalize trailing redundant blank lines at EOF on modified text files.

    POSIX and editor conventions mandate exactly one trailing newline at EOF.
    Tool abstractions sometimes append a redundant newline to already-terminated
    content (e.g. 'READY\\n\\n'); normalize trailing blank lines back to a single '\\n'.
    """
    if root is None:
        root = Path.cwd()
    skip_dirs = {".git", "__pycache__", ".pytest_cache", ".venv", "venv"}
    for path in root.rglob("*"):
        if not path.is_file() or any(p in path.parts for p in skip_dirs):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if content and (content.endswith("\n\n") or content.endswith("\r\n\r\n") or content.endswith("\n\r\n")):
            trimmed = content.rstrip("\r\n") + "\n"
            try:
                path.write_text(trimmed, encoding="utf-8", newline="\n")
            except OSError:
                pass


def main() -> int:
    instruction = sys.stdin.read().strip()
    if not instruction:
        print("missing task instruction on stdin", file=sys.stderr)
        return 2

    present = [name for name in FORBIDDEN_CLOUD_CREDENTIALS if os.environ.get(name)]
    if present:
        print(
            "cloud credentials forbidden in sovereign Hermes run: "
            + ", ".join(present),
            file=sys.stderr,
        )
        return 2

    try:
        hermes_bin = resolve_hermes_bin()
    except FileNotFoundError as exc:
        print(f"fail-closed: {exc}", file=sys.stderr)
        return 2

    if "HERMES_CONFIG" in os.environ:
        cfg_file = os.environ["HERMES_CONFIG"]
        if not Path(cfg_file).is_file():
            print(f"fail-closed: missing hermes config file: {cfg_file}", file=sys.stderr)
            return 2
    else:
        default_cfg = r"C:\Users\Mark\AppData\Local\hermes\config.yaml"
        cfg_file = default_cfg if Path(default_cfg).is_file() else str(Path.home() / ".hermes" / "config.yaml")
        if not Path(cfg_file).is_file():
            print(f"fail-closed: missing hermes config file: {cfg_file}", file=sys.stderr)
            return 2

    model = os.environ.get("HERMES_MODEL") or os.environ.get("MODEL_SPELUNKER_MODEL") or "bigmac/qwen3-coder-30b"
    if "/" in model:
        active_provider, model_name = model.split("/", 1)
    else:
        active_provider = os.environ.get("HERMES_PROVIDER", "bigmac")
        model_name = model

    # Validate active provider endpoint
    base_url = os.environ.get("HERMES_OPENAI_BASE_URL") or os.environ.get("HERMES_BASE_URL")
    if not base_url:
        # Inspect hermes config for provider base_url
        try:
            import ruamel.yaml as yaml_mod
            yaml = yaml_mod.YAML(typ="safe")
            cfg_data = yaml.load(Path(cfg_file).read_text(encoding="utf-8"))
        except Exception:
            try:
                import yaml
                cfg_data = yaml.safe_load(Path(cfg_file).read_text(encoding="utf-8"))
            except Exception:
                cfg_data = {}

        providers = cfg_data.get("providers", {})
        if active_provider not in providers and active_provider != "custom":
            print(f"fail-closed: active provider '{active_provider}' not declared in {cfg_file}", file=sys.stderr)
            return 2
        prov_cfg = providers.get(active_provider, {})
        base_url = prov_cfg.get("base_url") or prov_cfg.get("api")
        if not base_url and active_provider == "custom":
            base_url = cfg_data.get("model", {}).get("base_url")

    if not base_url:
        print(f"fail-closed: missing base_url for provider '{active_provider}'", file=sys.stderr)
        return 2

    try:
        validate_sovereign_endpoint(base_url)
    except ValueError as exc:
        print(f"fail-closed: target model base URL must be local/private: {exc}", file=sys.stderr)
        return 2

    api_key = resolve_sovereign_api_key(("HERMES_API_KEY", "BIGMAC_API_KEY"))

    toolsets = os.environ.get("HERMES_TOOLSETS", "file,terminal")

    command = [
        hermes_bin,
        "chat",
        "-q",
        instruction,
        "--provider",
        active_provider,
        "-m",
        model_name,
        "--base-url",
        base_url,
        "--api-key",
        api_key,
        "-t",
        toolsets,
        "--yolo",
        "--oneshot",
        "-Q",
    ]

    if os.environ.get("HERMES_MOCK_DRY_RUN") == "1":
        print(" ".join(command))
        return 0

    env = dict(os.environ)
    env["HERMES_HOME"] = str(Path(cfg_file).parent)
    env["HERMES_BASE_URL"] = base_url
    env["HERMES_API_KEY"] = api_key

    completed = subprocess.run(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    sanitize_workspace_trailing_whitespace()
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
