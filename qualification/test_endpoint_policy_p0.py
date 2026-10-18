#!/usr/bin/env python3
"""P0 Causal Falsification Tests: Endpoint Policy & Egress Containment (NET-01, NET-02, NET-03)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qualification.endpoint_policy import (
    validate_sovereign_endpoint,
    is_private_or_local_url,
    sanitize_candidate_env,
    resolve_sovereign_api_key,
    FORBIDDEN_CLOUD_CREDENTIALS,
    PROXY_VARIABLES,
    APP_ENDPOINT_PREFLIGHT,
    EGRESS_BOUNDARY_ATTESTED,
)


def test_net_01_prohibited_endpoints() -> None:
    """NET-01: Public cloud URLs, non-HTTP schemes, cloud metadata, and documentation IPs are rejected."""
    # Assert boundary honesty labels
    assert APP_ENDPOINT_PREFLIGHT == "PARTIAL", "Endpoint preflight must be labeled PARTIAL"
    assert EGRESS_BOUNDARY_ATTESTED == "NO", "Egress boundary attestation must be labeled NO"

    prohibited_cases = [
        ("https://api.openai.com/v1", "public DNS"),
        ("https://openrouter.ai/api/v1", "public DNS"),
        ("https://api.anthropic.com/v1", "public DNS"),
        ("http://169.254.169.254/latest/meta-data", "cloud metadata"),
        ("http://169.254.1.1:8080/v1", "link-local address"),
        ("http://203.0.113.10:8080/v1", "IANA documentation address TEST-NET-3"),
        ("http://198.51.100.1:8080/v1", "IANA documentation address TEST-NET-2"),
        ("http://192.0.2.1:8080/v1", "IANA documentation address TEST-NET-1"),
        ("http://100.64.0.1:8080/v1", "Carrier-Grade NAT address"),
        ("ftp://192.168.1.10/v1", "non-HTTP scheme"),
        ("file:///etc/passwd", "non-HTTP scheme"),
        ("gopher://192.168.1.10:8080", "non-HTTP scheme"),
        ("http://user:pass@192.168.1.10:8080/v1", "embedded user credentials"),
        ("http://8.8.8.8:8080/v1", "public IPv4"),
        ("http://1.1.1.1:8080/v1", "public IPv4"),
    ]

    for url, desc in prohibited_cases:
        try:
            validate_sovereign_endpoint(url)
            assert False, f"Expected validation failure for {desc}: {url}"
        except ValueError as exc:
            assert "fail-closed" in str(exc), f"Expected fail-closed in error message, got: {exc}"
        assert not is_private_or_local_url(url), f"is_private_or_local_url must return False for: {url}"

    # Verify authorized literal IP routes pass cleanly
    authorized_cases = [
        "http://127.0.0.1:8080/v1",
        "http://localhost:11434",
        "http://192.168.178.105:8080/v1",
        "http://192.168.1.50:8080/v1",
        "http://10.0.0.1:8080/v1",
        "http://172.16.0.1:8080/v1",
        "http://172.31.255.255:8080/v1",
    ]
    for url in authorized_cases:
        validate_sovereign_endpoint(url)
        assert is_private_or_local_url(url), f"Authorized URL failed validation: {url}"

    # Active DNS resolution falsification using unittest.mock
    from unittest.mock import patch
    import socket

    # 1. Hostname resolving to private RFC1918 address passes
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.42", 0))]):
        validate_sovereign_endpoint("http://sovereign-host.local:8080/v1")
        assert is_private_or_local_url("http://sovereign-host.local:8080/v1")

    # 2. Hostname resolving to public IP address fails closed
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]):
        try:
            validate_sovereign_endpoint("http://sneaky-public.local:8080/v1")
            assert False, "Expected fail-closed on public IP resolved from .local"
        except ValueError as exc:
            assert "fail-closed" in str(exc)
        assert not is_private_or_local_url("http://sneaky-public.local:8080/v1")

    # 3. Hostname that fails to resolve fails closed
    with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name resolution failed")):
        try:
            validate_sovereign_endpoint("http://unresolvable.local:8080/v1")
            assert False, "Expected fail-closed on unresolvable hostname"
        except ValueError as exc:
            assert "fail-closed: cannot resolve hostname" in str(exc)
        assert not is_private_or_local_url("http://unresolvable.local:8080/v1")

    print("PASS: NET-01 Prohibited endpoint rejection and authorized route validation")


def test_net_02_proxy_and_environment_sanitization() -> None:
    """NET-02: Proxy variables and cloud credentials are unconditionally scrubbed from candidate env."""
    dirty_env = {
        "PATH": "C:\\Windows\\System32",
        "SYSTEMROOT": "C:\\Windows",
        "SYSTEMDRIVE": "C:",
        "COMSPEC": "C:\\Windows\\System32\\cmd.exe",
        "TEMP": "C:\\Temp",
        "TMP": "C:\\Temp",
        "OPENROUTER_API_KEY": "sk-secret-openrouter",
        "ANTHROPIC_API_KEY": "sk-ant-secret",
        "GEMINI_API_KEY": "AIzaSySecret",
        "GOOGLE_API_KEY": "AIzaSySecret",
        "HTTP_PROXY": "http://evil-proxy:8080",
        "HTTPS_PROXY": "http://evil-proxy:8443",
        "ALL_PROXY": "socks5://evil-proxy:1080",
        "http_proxy": "http://evil-proxy:8080",
        "https_proxy": "http://evil-proxy:8443",
        "all_proxy": "socks5://evil-proxy:1080",
        "MY_ALLOWED_VAR": "safe_value",
        "UNSAFE_CUSTOM_SECRET": "should_be_stripped_in_minimal_mode",
    }

    # Test inherit mode
    cleaned_inherit = sanitize_candidate_env(dirty_env, mode="inherit")
    for key in FORBIDDEN_CLOUD_CREDENTIALS:
        assert key not in cleaned_inherit, f"{key} was not scrubbed in inherit mode"
    for key in PROXY_VARIABLES:
        assert key not in cleaned_inherit, f"{key} was not scrubbed in inherit mode"
    assert cleaned_inherit["MY_ALLOWED_VAR"] == "safe_value"
    assert cleaned_inherit["UNSAFE_CUSTOM_SECRET"] == "should_be_stripped_in_minimal_mode"

    # Test minimal mode
    cleaned_minimal = sanitize_candidate_env(dirty_env, mode="minimal", pass_env=["MY_ALLOWED_VAR"])
    for key in FORBIDDEN_CLOUD_CREDENTIALS:
        assert key not in cleaned_minimal, f"{key} was not scrubbed in minimal mode"
    for key in PROXY_VARIABLES:
        assert key not in cleaned_minimal, f"{key} was not scrubbed in minimal mode"
    assert "PATH" in cleaned_minimal
    if os.name == "nt":
        assert "SYSTEMROOT" in cleaned_minimal
    assert cleaned_minimal["MY_ALLOWED_VAR"] == "safe_value"
    # Unallowed variable MUST be dropped in minimal mode
    assert "UNSAFE_CUSTOM_SECRET" not in cleaned_minimal, "Unsafe custom var leaked into minimal env"

    print("PASS: NET-02 Proxy scrubbing and minimal environment containment")


def test_net_03_secret_isolation_in_argv_and_diagnostics() -> None:
    """NET-03: Adapters must not pass API keys in command-line arguments (argv) and block unauthorized egress."""
    adapters_dir = ROOT / "qualification" / "adapters"

    env = dict(os.environ)
    for k in FORBIDDEN_CLOUD_CREDENTIALS:
        env.pop(k, None)

    # Test Aider dry-run secret isolation
    with tempfile.TemporaryDirectory() as td:
        fake_bin = Path(td) / "fake_aider.exe"
        fake_bin.write_text("", encoding="utf-8")
        env["AIDER_BIN"] = str(fake_bin)
        env["AIDER_MOCK_DRY_RUN"] = "1"
        env["AIDER_OPENAI_API_KEY"] = "sk-test-secret-key-12345"

        res = subprocess.run(
            [sys.executable, str(adapters_dir / "aider_cli.py")],
            input="Fix bug",
            text=True,
            capture_output=True,
            env=env,
        )
        assert res.returncode == 0, f"Aider dry-run failed: {res.stderr}"
        assert "sk-test-secret-key-12345" not in res.stdout, "Secret API key leaked into Aider argv output!"
        assert "--openai-api-key" not in res.stdout, "--openai-api-key must not be passed in argv!"

    # Test Qwen dry-run secret isolation
    with tempfile.TemporaryDirectory() as td:
        fake_bin = Path(td) / "fake_qwen.cmd"
        fake_bin.write_text("", encoding="utf-8")
        env["QWEN_BIN"] = str(fake_bin)
        env["QWEN_MOCK_DRY_RUN"] = "1"
        env["QWEN_OPENAI_API_KEY"] = "sk-test-secret-key-67890"

        res = subprocess.run(
            [sys.executable, str(adapters_dir / "qwen_cli.py")],
            input="Fix bug",
            text=True,
            capture_output=True,
            env=env,
        )
        assert res.returncode == 0, f"Qwen dry-run failed: {res.stderr}"
        assert "sk-test-secret-key-67890" not in res.stdout, "Secret API key leaked into Qwen argv output!"
        assert "--openai-api-key" not in res.stdout, "--openai-api-key must not be passed in argv!"

    # Test outbound egress block: adapter rejects public cloud URL configuration fail-closed
    with tempfile.TemporaryDirectory() as td:
        fake_bin = Path(td) / "fake_goose.exe"
        fake_bin.write_text("", encoding="utf-8")
        bad_env = dict(env)
        bad_env["GOOSE_BIN"] = str(fake_bin)
        bad_env["GOOSE_MOCK_DRY_RUN"] = "1"
        bad_env["OLLAMA_HOST"] = "https://api.openai.com/v1"

        res = subprocess.run(
            [sys.executable, str(adapters_dir / "goose_cli.py")],
            input="Fix bug",
            text=True,
            capture_output=True,
            env=bad_env,
        )
        assert res.returncode != 0, "Adapter should fail closed on public egress configuration"
        assert "fail-closed" in res.stderr

    print("PASS: NET-03 Secret isolation in argv, diagnostics, and outbound egress blocks")


def test_net_04_sovereign_api_key_cloud_fallback_rejected() -> None:
    """CRED-FALLBACK: Generic OPENAI_API_KEY must not be projected as sovereign key; cloud keys fail closed."""
    orig_env = dict(os.environ)
    try:
        os.environ.pop("BIGMAC_API_KEY", None)
        os.environ.pop("SOVEREIGN_API_KEY", None)
        os.environ["OPENAI_API_KEY"] = "sk-proj-cloud-secret-key-123"

        # resolve_sovereign_api_key without explicit keys must NOT return the cloud OPENAI_API_KEY
        resolved = resolve_sovereign_api_key()
        assert resolved != "sk-proj-cloud-secret-key-123", "Cloud OPENAI_API_KEY was projected as sovereign key!"

        # Attempting to pass cloud key explicitly fails closed
        try:
            resolve_sovereign_api_key(("OPENAI_API_KEY",))
            raise AssertionError("Cloud key should fail closed in resolve_sovereign_api_key")
        except ValueError as exc:
            assert "fail-closed" in str(exc)

        # Legitimate sovereign key resolves
        os.environ["BIGMAC_API_KEY"] = "local-sovereign-valid-key"
        resolved_sovereign = resolve_sovereign_api_key()
        assert resolved_sovereign == "local-sovereign-valid-key"
    finally:
        os.environ.clear()
        os.environ.update(orig_env)

    print("PASS: NET-04 (CRED-FALLBACK) Sovereign API key rejects cloud fallback and projection")


if __name__ == "__main__":
    test_net_01_prohibited_endpoints()
    test_net_02_proxy_and_environment_sanitization()
    test_net_03_secret_isolation_in_argv_and_diagnostics()
    test_net_04_sovereign_api_key_cloud_fallback_rejected()
    print("ALL P0 Endpoint Policy & Egress tests PASS (NET-01..NET-04, CRED-FALLBACK)")
