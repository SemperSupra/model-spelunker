#!/usr/bin/env python3
"""Shared endpoint policy and environment sanitization for sovereign actor qualification."""

from __future__ import annotations

import ipaddress
import json
import os
import sys
import urllib.parse
from pathlib import Path


# Explicit forbidden cloud credential keys that must never be passed to sovereign actors
FORBIDDEN_CLOUD_CREDENTIALS = (
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AZURE_OPENAI_API_KEY",
)

# Proxy environment variables that must be scrubbed to prevent unauthorized network diversion
PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)

# Standard RFC1918 private IPv4 networks
RFC1918_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)

# Prohibited address spaces (even if some libraries flag them as 'private')
PROHIBITED_NETWORKS = (
    ipaddress.IPv4Network("169.254.0.0/16"),   # IPv4 Link-Local / Cloud Instance Metadata (e.g. 169.254.169.254)
    ipaddress.IPv4Network("192.0.2.0/24"),     # TEST-NET-1 (IANA documentation)
    ipaddress.IPv4Network("198.51.100.0/24"),  # TEST-NET-2 (IANA documentation)
    ipaddress.IPv4Network("203.0.113.0/24"),   # TEST-NET-3 (IANA documentation)
    ipaddress.IPv4Network("100.64.0.0/10"),    # Shared Address Space / Carrier-Grade NAT
    ipaddress.IPv4Network("224.0.0.0/4"),      # Multicast
    ipaddress.IPv4Network("0.0.0.0/8"),        # This network
    ipaddress.IPv4Network("240.0.0.0/4"),      # Reserved
)


def validate_sovereign_endpoint(url_string: str) -> None:
    """Validate that target model URL strictly resolves to an authorized RFC1918 or loopback route.

    Fails closed on:
    - Non-HTTP/HTTPS schemes
    - URLs containing userinfo (credentials in URL)
    - Cloud metadata / link-local addresses (169.254.x.x)
    - IANA documentation addresses (203.0.113.x, etc.)
    - Carrier-grade NAT / shared address space (100.64.x.x)
    - Public / internet routable IP addresses
    - Unresolved or non-local hostnames
    """
    if not url_string or not isinstance(url_string, str):
        raise ValueError("endpoint URL must be a non-empty string")

    parsed = urllib.parse.urlparse(url_string)

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"fail-closed: unauthorized URL scheme '{parsed.scheme}'; only http and https are permitted")

    if parsed.username or parsed.password:
        raise ValueError("fail-closed: endpoint URL must not contain embedded user credentials")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError(f"fail-closed: invalid or missing hostname in endpoint URL: {url_string}")

    # Allow loopback names directly
    if hostname in {"127.0.0.1", "localhost", "::1"}:
        return

    # Check if hostname is an IP address
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        # Not a raw IP literal. Allow known local mDNS/hostnames only if strictly local
        if hostname.endswith(".local"):
            return
        raise ValueError(
            f"fail-closed: public DNS names or non-local hostnames are prohibited for sovereign inference: {hostname}"
        )

    # IPv6 loopback is allowed
    if ip.is_loopback:
        return

    if ip.version != 4:
        raise ValueError(f"fail-closed: only IPv4 RFC1918 and loopback are permitted; got IPv6 {ip}")

    # Check against prohibited networks (metadata, doc, cgnat, multicast)
    for prohibited in PROHIBITED_NETWORKS:
        if ip in prohibited:
            raise ValueError(f"fail-closed: prohibited network address {ip} in {prohibited}")

    # Check against authorized RFC1918 networks
    for rfc1918 in RFC1918_NETWORKS:
        if ip in rfc1918:
            return

    raise ValueError(f"fail-closed: target model IP address {ip} is not in RFC1918 or loopback space")


def is_private_or_local_url(url_string: str) -> bool:
    """Boolean wrapper around validate_sovereign_endpoint for backward compatibility."""
    try:
        validate_sovereign_endpoint(url_string)
        return True
    except (ValueError, Exception):
        return False


def sanitize_candidate_env(
    base_env: dict[str, str],
    mode: str = "inherit",
    pass_env: list[str] | None = None,
) -> dict[str, str]:
    """Sanitize environment variables for candidate execution.

    - Strips all known cloud provider API credentials.
    - Strips network proxy variables to prevent routing diversion.
    - If mode == 'minimal', restricts to essential system variables + pass_env.
    """
    pass_keys = set(pass_env or [])

    if mode == "minimal":
        if os.name == "nt":
            allowed_baseline = {
                "PATH",
                "SYSTEMROOT",
                "COMSPEC",
                "PATHEXT",
                "TEMP",
                "TMP",
                "PROCESSOR_IDENTIFIER",
                "USERPROFILE",
                "LOCALAPPDATA",
                "APPDATA",
            }
        else:
            allowed_baseline = {
                "PATH",
                "HOME",
                "LANG",
                "LC_ALL",
                "TMPDIR",
                "USER",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
            }
        allowed = allowed_baseline | pass_keys
        sanitized = {k: v for k, v in base_env.items() if k in allowed}
    else:
        sanitized = dict(base_env)

    # Unconditionally scrub forbidden cloud credentials and proxy variables
    for key in FORBIDDEN_CLOUD_CREDENTIALS:
        sanitized.pop(key, None)
    for key in PROXY_VARIABLES:
        sanitized.pop(key, None)

    return sanitized


def resolve_sovereign_api_key(explicit_keys: tuple[str, ...] = ()) -> str:
    """Dynamically resolve local sovereign API key without printing or committing secrets."""
    for key_name in explicit_keys:
        val = os.environ.get(key_name)
        if val:
            return val
    for fallback_name in ("BIGMAC_API_KEY", "OPENAI_API_KEY"):
        val = os.environ.get(fallback_name)
        if val:
            return val

    endpoint_config = Path.home() / ".local" / "sovereign-actors" / "config" / "endpoint.json"
    if endpoint_config.is_file():
        try:
            data = json.loads(endpoint_config.read_text(encoding="utf-8"))
            key = data.get("endpoints", {}).get("bigmac", {}).get("api_key")
            if key:
                return str(key)
        except Exception:
            pass

    return "local-sovereign-dummy-key"
