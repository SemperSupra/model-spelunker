#!/usr/bin/env python3
"""Project one hosted qualification receipt into Foundry hosted-realization semantics."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def observed_at(run_id: str) -> str:
    stamp = run_id.split("-", 1)[0]
    dt = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def project(actor: dict, receipt: dict) -> dict:
    model = actor["model"]
    if model.get("realization") == "local-artifact":
        raise ValueError("hosted-realization projection requires a hosted or router actor")

    env = actor["execution_environment"]
    route_name = str(env["inference_route"])
    workload = receipt.get("observation", {}).get("workload") or {}
    resolved = list(workload.get("resolved_models") or [])
    fingerprints = list(workload.get("system_fingerprints") or [])
    providers = list(workload.get("serving_providers") or [])

    route_mode = "intermediary" if route_name.startswith("openrouter") else "direct"
    resolved_model = resolved[0] if len(resolved) == 1 else None
    fingerprint = fingerprints[0] if len(fingerprints) == 1 else None
    upstream = providers[0] if route_mode == "intermediary" and len(providers) == 1 else None

    requested = str(model["id"])
    if model.get("realization") == "router" and resolved_model is None:
        strength = "ROUTED_UNKNOWN"
    elif any(marker in requested.lower() for marker in ("latest", "preview", "experimental")):
        strength = "MUTABLE_ALIAS"
    elif fingerprint:
        strength = "FINGERPRINTED_HOSTED"
    else:
        strength = "NAMED_HOSTED"

    return {
        "schema_version": 1,
        "kind": "hosted-realization",
        "provider": str(model["provider"]),
        "requested_model": requested,
        "resolved_model": resolved_model,
        "provider_model_version": None,
        "system_fingerprint": fingerprint,
        "api_interface": route_name,
        "service_tier": (
            workload["service_tiers"][0]
            if len(workload.get("service_tiers") or []) == 1
            else None
        ),
        "observed_at": observed_at(receipt["run_id"]),
        "provenance_strength": strength,
        "route": {
            "mode": route_mode,
            "intermediary": "openrouter" if route_mode == "intermediary" else None,
            "upstream_provider": upstream,
            "fallback_observed": None,
        },
        "evidence": {
            "source": receipt["run_id"],
            "response_metadata_digest": None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("actor_profile", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    actor = json.loads(args.actor_profile.read_text(encoding="utf-8"))
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    value = project(actor, receipt)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
