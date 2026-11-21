#!/usr/bin/env python3
"""Public, unauthenticated OpenRouter catalog admission; never invokes inference."""
from __future__ import annotations
import argparse
import json
import sys
import urllib.error
import urllib.request

CANDIDATES = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "particle-ai/particle-1:free",
    "recursive/flint-v1.0:free",
    "google/gemma-4-26b-a4b-it:free",
)
ENDPOINT = "https://openrouter.ai/api/v1/models"

def classify(catalog):
    if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
        raise ValueError("invalid catalog envelope")
    rows = catalog["data"]
    exact = {}
    for entry in rows:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            if entry["id"] in exact:
                raise ValueError("duplicate exact model id")
            exact[entry["id"]] = entry
    results = []
    for ident in CANDIDATES:
        row = exact.get(ident)
        if row is None:
            results.append({"model": ident, "state": "MISSING"})
            continue
        pricing = row.get("pricing")
        params = row.get("supported_parameters")
        try:
            zero = isinstance(pricing, dict) and float(pricing["prompt"]) == 0 and float(pricing["completion"]) == 0
        except (TypeError, ValueError, KeyError):
            zero = False
        tools = isinstance(params, list) and "tools" in params
        context = row.get("context_length")
        usable_context = type(context) is int and context >= 32768
        results.append({
            "model": ident,
            "state": "CATALOG_READY" if zero and tools and usable_context else "NOT_ADMITTED",
            "zero_prompt_completion": zero,
            "supports_tools": tools,
            "context_tokens": context if usable_context else None,
        })
    return {"schema": "openrouter-free-public-census/v1",
            "disclosure": "PUBLIC_CATALOG_ONLY",
            "authenticated": False, "model_inference": False,
            "models": results}

def selftest():
    def make(ident, price="0", tools=True, context=65536):
        return {"id": ident, "pricing": {"prompt": price, "completion": "0"},
                "supported_parameters": ["tools"] if tools else [], "context_length": context}
    base={"data":[make(x) for x in CANDIDATES]}
    check=classify(base)
    assert all(x["state"]=="CATALOG_READY" for x in check["models"])
    bad={"data":[make(CANDIDATES[0],price="0.0001"), make(CANDIDATES[1], tools=False), make(CANDIDATES[2],context=4096)]}
    result=classify(bad)
    assert [x["state"] for x in result["models"]]==["NOT_ADMITTED","NOT_ADMITTED","NOT_ADMITTED","MISSING"]
    for malformed in ({}, {"data":{}}, {"data":[make(CANDIDATES[0]),make(CANDIDATES[0])]}):
        try:classify(malformed)
        except ValueError:pass
        else:raise AssertionError("invalid catalog admitted")
    serialized=json.dumps(check)
    assert not any(x in serialized.lower() for x in ("api_key", "authorization", "secret_value"))
    print(json.dumps({"state":"PASS","kind":"offline-negative-catalog-oracle","cases":7}))
def live():
    req=urllib.request.Request(ENDPOINT,headers={"Accept":"application/json","User-Agent":"Model-Spelunker-Public-Catalog/1"},method="GET")
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            result=classify(json.load(response))
    except (urllib.error.URLError,TimeoutError,ValueError) as exc:
        result={"schema":"openrouter-free-public-census/v1","state":"CATALOG_UNAVAILABLE",
                "error_type":type(exc).__name__,"authenticated":False,"model_inference":False}
    print(json.dumps(result,sort_keys=True))
    # A catalog failure or inaccessible endpoint is retained as censorship, not a model failure.
    return 0

def main():
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--selftest",action="store_true")
    group.add_argument("--live",action="store_true")
    args=p.parse_args()
    if args.selftest:selftest()
    else:sys.exit(live())

if __name__=="__main__":main()
