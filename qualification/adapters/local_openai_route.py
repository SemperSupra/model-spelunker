"""Explicit local OpenAI-compatible model route for configured-actor interviews.

No silent default-provider behavior and no environment-derived cloud endpoint.
This is a *client guard*, not a network sandbox or proof of model sovereignty.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Mapping
from urllib.parse import urlsplit


class LocalOpenAIRouteHold(ValueError):
    """Redacted route refusal; never include URL, hostname, or credentials."""


def _approved_local_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    allowed = (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "fc00::/7",
        "::1/128",
    )
    return any(address in ipaddress.ip_network(block) for block in allowed)


def resolve_local_openai_route(
    model_ref: str, environ: Mapping[str, str]
) -> tuple[str, str, str]:
    """Resolve (bare model ID, endpoint, key) for one explicit local treatment.

    Names are generic and public-safe. Secret values and endpoint identities
    belong in the calling runtime, not the repository or evidence receipt.
    """
    prefix, separator, model = model_ref.partition(":")
    if prefix != "local-openai" or not separator or not model:
        raise LocalOpenAIRouteHold("LOCAL_MODEL_BINDING_REQUIRED")
    if len(model) > 160 or any(ch.isspace() or ord(ch) < 32 for ch in model):
        raise LocalOpenAIRouteHold("LOCAL_MODEL_ID_INVALID")

    endpoint = (environ.get("MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL") or "").strip()
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise LocalOpenAIRouteHold("LOCAL_ENDPOINT_FORMAT_HOLD") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or not parsed.netloc
        or port == 0
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise LocalOpenAIRouteHold("LOCAL_ENDPOINT_FORMAT_HOLD")

    api_key = environ.get("MODEL_SPELUNKER_LOCAL_OPENAI_API_KEY") or ""
    if api_key and parsed.scheme != "https":
        raise LocalOpenAIRouteHold("LOCAL_AUTHENTICATED_HTTP_HOLD")

    # The pinned OpenWorker source creates a stock OpenAI SDK client without
    # setting httpx trust_env=False. Its transport can therefore inherit
    # HTTP(S)_PROXY/ALL_PROXY and send even a private URL through an external
    # proxy. This treatment refuses that ambient route rather than assuming
    # NO_PROXY will always be honored. Do not log proxy values.
    proxy_keys = {"http_proxy", "https_proxy", "all_proxy"}
    if any(key.lower() in proxy_keys and value for key, value in environ.items()):
        raise LocalOpenAIRouteHold("LOCAL_AMBIENT_PROXY_HOLD")

    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(
                parsed.hostname, port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, ValueError):
        raise LocalOpenAIRouteHold("LOCAL_RESOLUTION_HOLD") from None
    if not addresses or not all(_approved_local_ip(addr) for addr in addresses):
        raise LocalOpenAIRouteHold("LOCAL_PRIVATE_ROUTE_REQUIRED")

    # The placeholder key is never an authority token. Existing local endpoints
    # may require no authentication; private gateway tokens require HTTPS.
    return model, endpoint.rstrip("/"), api_key or "local-no-auth"
