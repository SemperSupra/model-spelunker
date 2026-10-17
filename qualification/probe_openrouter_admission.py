#!/usr/bin/env python3
"""Zero-cost preflight admission gate for OpenRouter endpoints.

Ensures that models are live, zero-priced (when expected), and strictly pinned
without silent provider fallback before any stochastic task execution begins.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

def get_api_key() -> str:
    # Resolve from environment or secrets file (zero-secret committed)
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    secrets_path = os.path.expanduser("~/.config/goose/secrets.yaml")
    if os.path.exists(secrets_path):
        with open(secrets_path, "r") as f:
            for line in f:
                if "OPENROUTER_API_KEY" in line:
                    return line.split(":", 1)[1].strip().strip('"').strip("'")
    return ""

def fetch_catalog() -> Dict[str, Any]:
    req = urllib.request.Request(OPENROUTER_MODELS_URL, headers={"User-Agent": "model-spelunker/preflight"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {m["id"]: m for m in data.get("data", [])}

def evaluate_model_admission(model_id: str, catalog: Dict[str, Any], require_zero_cost: bool = True) -> Dict[str, Any]:
    if model_id not in catalog:
        return {
            "model_id": model_id,
            "admitted": False,
            "classification": "ADMISSION_NOT_IN_CATALOG",
            "reason": f"Model {model_id} not found in live OpenRouter catalog"
        }
    
    entry = catalog[model_id]
    pricing = entry.get("pricing", {})
    prompt_price = float(pricing.get("prompt", 0))
    completion_price = float(pricing.get("completion", 0))
    
    is_zero_cost = (prompt_price == 0.0 and completion_price == 0.0)
    if require_zero_cost and not is_zero_cost:
        return {
            "model_id": model_id,
            "admitted": False,
            "classification": "ADMISSION_PRICING_VIOLATION",
            "reason": f"Expected zero-cost model, but found prompt={prompt_price}, completion={completion_price}",
            "pricing": pricing
        }
        
    context_length = entry.get("context_length", 0)
    architecture = entry.get("architecture", {})
    
    return {
        "model_id": model_id,
        "admitted": True,
        "classification": "ADMISSION_PASS",
        "context_length": context_length,
        "pricing": pricing,
        "is_zero_cost": is_zero_cost,
        "tokenizer": architecture.get("tokenizer"),
        "instruct_type": architecture.get("instruct_type")
    }

def check_key_status(api_key: str) -> Dict[str, Any]:
    if not api_key:
        return {"configured": False, "status": "NO_KEY"}
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "model-spelunker/preflight"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data", {})
            return {
                "configured": True,
                "status": "VALID",
                "label": data.get("label"),
                "is_free_tier": data.get("is_free_tier"),
                "usage": data.get("usage"),
                "limit": data.get("limit"),
                "rate_limit": data.get("rate_limit")
            }
    except urllib.error.HTTPError as e:
        return {
            "configured": True,
            "status": f"HTTP_{e.code}",
            "reason": e.read().decode("utf-8", errors="replace")
        }
    except Exception as e:
        return {"configured": True, "status": "NETWORK_ERROR", "reason": str(e)}

def list_free_models(catalog: Dict[str, Any]) -> None:
    free_models = []
    for mid, m in catalog.items():
        pricing = m.get("pricing", {})
        if float(pricing.get("prompt", 0) or 0) == 0 and float(pricing.get("completion", 0) or 0) == 0:
            free_models.append((mid, m.get("context_length", 0), m.get("name", "")))
    print(f"\nDiscovered {len(free_models)} zero-cost (:free) models in live catalog:")
    for mid, ctx, name in sorted(free_models):
        print(f"  • {mid:<55} (ctx: {ctx:,} tok) [{name}]")
    print()

def probe_live_inference(model_id: str, api_key: str, provider_pin: Optional[str] = None) -> Dict[str, Any]:
    if not api_key:
        return {
            "live_probe": False,
            "classification": "PROBE_SKIPPED_NO_KEY",
            "reason": "OPENROUTER_API_KEY not configured"
        }
        
    extra_body = {"provider": {"allow_fallbacks": False}}
    if provider_pin:
        extra_body["provider"]["only"] = [provider_pin]
        
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0.0,
        **extra_body
    }
    
    req = urllib.request.Request(
        OPENROUTER_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/SemperSupra/model-spelunker",
            "X-Title": "model-spelunker-admission"
        }
    )
    
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = time.perf_counter() - t0
            raw_headers = dict(resp.headers)
            gas_telemetry = {
                "remaining_requests": raw_headers.get("x-ratelimit-remaining-requests"),
                "limit_requests": raw_headers.get("x-ratelimit-limit-requests"),
                "reset_requests_seconds": raw_headers.get("x-ratelimit-reset-requests"),
                "remaining_tokens": raw_headers.get("x-ratelimit-remaining-tokens"),
                "limit_tokens": raw_headers.get("x-ratelimit-limit-tokens"),
                "reset_tokens_seconds": raw_headers.get("x-ratelimit-reset-tokens"),
            }
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "live_probe": True,
                "latency_seconds": elapsed,
                "classification": "PROBE_PASS",
                "resolved_model": data.get("model"),
                "resolved_provider": data.get("provider"),
                "gas_telemetry": {k: v for k, v in gas_telemetry.items() if v is not None}
            }
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        raw_headers = dict(e.headers)
        return {
            "live_probe": False,
            "classification": f"HTTP_{e.code}",
            "reason": err_msg,
            "retry_after": raw_headers.get("retry-after")
        }
    except Exception as e:
        return {
            "live_probe": False,
            "classification": "NETWORK_ERROR",
            "reason": str(e)
        }

def main() -> int:
    parser = argparse.ArgumentParser(description="Zero-cost OpenRouter preflight admission probe")
    parser.add_argument("models", nargs="*", default=[], help="Model IDs to probe")
    parser.add_argument("--list-free", action="store_true", help="List all zero-cost models currently in the catalog")
    parser.add_argument("--require-zero-cost", action="store_true", default=True, help="Enforce 0 prompt/completion pricing")
    parser.add_argument("--probe-live", action="store_true", help="Execute 1-token live probe with strict fallback disabled")
    parser.add_argument("--check-key", action="store_true", help="Check API key status and account limits via /api/v1/key")
    parser.add_argument("--provider-pin", help="Strictly require specific provider (e.g. 'groq' or 'deepseek')")
    parser.add_argument("--out", help="Write receipt JSON to path")
    args = parser.parse_args()
    
    print("Fetching live OpenRouter model catalog...")
    try:
        catalog = fetch_catalog()
        print(f"Catalog fetched: {len(catalog)} models online.")
    except Exception as e:
        print(f"Failed to fetch OpenRouter catalog: {e}", file=sys.stderr)
        return 1

    if args.list_free:
        list_free_models(catalog)
        if not args.models:
            return 0
        
    api_key = get_api_key()
    key_info = check_key_status(api_key) if (args.check_key or (args.probe_live and api_key)) else None
    if key_info:
        print(f"Key status: {key_info['status']} (free_tier={key_info.get('is_free_tier')}, rate_limit={key_info.get('rate_limit')})")

    results = {}
    all_admitted = True
    
    for model_id in args.models:
        status = evaluate_model_admission(model_id, catalog, require_zero_cost=args.require_zero_cost)
        if not status["admitted"]:
            all_admitted = False
            print(f"[-] {model_id}: REJECTED ({status['classification']} - {status['reason']})")
        else:
            print(f"[+] {model_id}: ADMITTED (ctx={status['context_length']}, zero_cost={status['is_zero_cost']})")
            if args.probe_live:
                probe_res = probe_live_inference(model_id, api_key, args.provider_pin)
                status["probe"] = probe_res
                print(f"    Live probe: {probe_res['classification']}")
                if "gas_telemetry" in probe_res:
                    gas = probe_res["gas_telemetry"]
                    print(f"    Gas gauge: {gas.get('remaining_requests', '?')} reqs / {gas.get('remaining_tokens', '?')} toks remaining")
                if not probe_res.get("live_probe"):
                    all_admitted = False
        results[model_id] = status
        
    receipt = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "probe_version": "openrouter-admission/v1",
        "all_admitted": all_admitted,
        "results": results
    }
    
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(receipt, f, indent=2)
        print(f"Receipt written to {args.out}")
        
    return 0 if all_admitted else 2

if __name__ == "__main__":
    sys.exit(main())
