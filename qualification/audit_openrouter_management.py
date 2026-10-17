#!/usr/bin/env python3
"""Programmatic audit tool for OpenRouter BYOK and workspace API keys.

Uses the OpenRouter Management API (GET /api/v1/byok and GET /api/v1/keys)
to audit configured upstream provider credentials and active inference keys.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional

OPENROUTER_BYOK_URL = "https://openrouter.ai/api/v1/byok"
OPENROUTER_KEYS_URL = "https://openrouter.ai/api/v1/keys"


def resolve_management_key(explicit_key: Optional[str] = None) -> str:
    if explicit_key:
        return explicit_key.strip()
    if os.environ.get("OPENROUTER_MANAGEMENT_KEY"):
        return os.environ["OPENROUTER_MANAGEMENT_KEY"].strip()
    secrets_path = Path.home() / ".config" / "goose" / "secrets.yaml"
    if secrets_path.exists():
        try:
            with open(secrets_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "OPENROUTER_MANAGEMENT_KEY" in line and ":" in line:
                        return line.split(":", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


def query_endpoint(url: str, key: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    full_url = url
    if params:
        query_string = urllib.parse.urlencode(params)
        full_url = f"{url}?{query_string}"
        
    req = urllib.request.Request(
        full_url,
        headers={
            "Authorization": f"Bearer {key}",
            "User-Agent": "model-spelunker/management-audit",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {
                "status": "OK",
                "code": resp.status,
                "data": json.loads(resp.read().decode("utf-8"))
            }
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {
            "status": "HTTP_ERROR",
            "code": e.code,
            "error": err_body
        }
    except Exception as e:
        return {
            "status": "NETWORK_ERROR",
            "code": 0,
            "error": str(e)
        }


def audit_byok_credentials(key: str) -> Dict[str, Any]:
    res = query_endpoint(OPENROUTER_BYOK_URL, key, {"limit": 100})
    if res["status"] != "OK":
        return res
    raw_data = res["data"].get("data", [])
    credentials = []
    for item in raw_data:
        credentials.append({
            "id": item.get("id"),
            "provider": item.get("provider"),
            "created_at": item.get("created_at"),
            "allowed_models": item.get("allowed_models"),
            "allowed_user_ids": item.get("allowed_user_ids"),
            "declared_region": item.get("declared_region")
        })
    return {"status": "OK", "count": len(credentials), "credentials": credentials}


def audit_workspace_keys(key: str) -> Dict[str, Any]:
    res = query_endpoint(OPENROUTER_KEYS_URL, key, {"include_disabled": "false"})
    if res["status"] != "OK":
        return res
    raw_data = res["data"].get("data", [])
    keys = []
    for item in raw_data:
        keys.append({
            "name": item.get("name") or item.get("label"),
            "hash": item.get("hash") or item.get("id"),
            "usage": item.get("usage"),
            "limit": item.get("limit"),
            "is_free_tier": item.get("is_free_tier"),
            "rate_limit": item.get("rate_limit"),
            "created_at": item.get("created_at")
        })
    return {"status": "OK", "count": len(keys), "keys": keys}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit OpenRouter BYOK and workspace API keys via Management API")
    parser.add_argument("--key", help="OpenRouter Management API key (or set OPENROUTER_MANAGEMENT_KEY)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--out", help="Write receipt JSON to path")
    args = parser.parse_args()

    mgmt_key = resolve_management_key(args.key)
    if not mgmt_key:
        print("ERROR: No OpenRouter Management Key provided.", file=sys.stderr)
        print("Set OPENROUTER_MANAGEMENT_KEY in your environment, ~/.config/goose/secrets.yaml, or pass --key.", file=sys.stderr)
        return 1

    print("Querying OpenRouter Management API...")
    byok_res = audit_byok_credentials(mgmt_key)
    keys_res = audit_workspace_keys(mgmt_key)

    report = {
        "timestamp_utc": time_utc(),
        "byok_audit": byok_res,
        "keys_audit": keys_res
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("\n" + "=" * 70)
        print("OPENROUTER BYOK (BRING YOUR OWN KEY) CREDENTIALS")
        print("=" * 70)
        if byok_res["status"] == "OK":
            creds = byok_res.get("credentials", [])
            print(f"Total BYOK credentials configured: {len(creds)}")
            if not creds:
                print("  (No BYOK credentials registered in this workspace)")
            for c in creds:
                prov = c.get("provider", "unknown")
                cid = c.get("id", "unknown")
                created = c.get("created_at", "")
                models = c.get("allowed_models") or "all models"
                print(f"  • Provider: {prov:<15} [ID: {cid}]")
                print(f"    Created: {created} | Models: {models}")
        else:
            print(f"  Failed to retrieve BYOK credentials: {byok_res.get('error')}")

        print("\n" + "=" * 70)
        print("OPENROUTER WORKSPACE INFERENCE KEYS")
        print("=" * 70)
        if keys_res["status"] == "OK":
            keys = keys_res.get("keys", [])
            print(f"Total active inference keys: {len(keys)}")
            for k in keys:
                name = k.get("name") or "(unnamed key)"
                usage = k.get("usage", 0.0)
                limit = k.get("limit")
                limit_str = f"${limit}" if limit is not None else "Unlimited"
                free_tier = k.get("is_free_tier", False)
                print(f"  • Key: {name:<25} Usage: ${usage:.4f} / Limit: {limit_str} (free_tier={free_tier})")
        else:
            print(f"  Failed to retrieve inference keys: {keys_res.get('error')}")
        print("=" * 70 + "\n")

    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Receipt written to {args.out}")

    return 0 if (byok_res.get("status") == "OK" and keys_res.get("status") == "OK") else 2


def time_utc() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    sys.exit(main())
