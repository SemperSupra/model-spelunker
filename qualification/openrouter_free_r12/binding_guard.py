#!/usr/bin/env python3
"""Prevent catalog/census identity drift before any protected OpenRouter API interview.

No credentials, inference, API calls, mutations, secrets, or provider account metadata.
"""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "qualification/models/hosted-api.json"
CENSUS = ROOT / "qualification/openrouter_free_r11/catalog_census.py"
WORKFLOW = ROOT / ".github/workflows/openworker-hosted-api-qualification.yml"

EXPECTED = {
    "openrouter-nvidia-nemotron3-ultra-free": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter-particle-1-free": "particle-ai/particle-1:free",
    "openrouter-recursive-flint-free": "recursive/flint-v1.0:free",
    "openrouter-google-gemma4-26b-a4b-free": "google/gemma-4-26b-a4b-it:free",
}

def assert_binding(candidates: dict, observed: tuple[str, ...]) -> None:
    if len(observed) != len(set(observed)):
        raise ValueError("duplicate census model")
    if set(observed) != set(EXPECTED.values()):
        raise ValueError("census and admissible model set diverge")
    for candidate_id, model in EXPECTED.items():
        row = candidates.get(candidate_id)
        if not isinstance(row, dict):
            raise ValueError("missing configured candidate")
        if row.get("model") != model:
            raise ValueError("catalog/census model identity mismatch")
        if row.get("treatment_kind") != "model" or row.get("provider") != "openrouter":
            raise ValueError("model treatment/provider identity mismatch")
        if row.get("api_base") != "https://openrouter.ai/api/v1":
            raise ValueError("provider endpoint changed")
        if row.get("cost_class") != "zero-token-price":
            raise ValueError("paid or unknown cost class")
        if not model.endswith(":free"):
            raise ValueError("nonfree model id")
        if row.get("extra_body") or row.get("route_fallback"):
            raise ValueError("unreviewed provider routing or fallback")

def test_negatives(base: dict, observed: tuple[str, ...]) -> int:
    count=0
    for identifier, field, bad in (
        ("openrouter-particle-1-free","model","openrouter/free"),
        ("openrouter-recursive-flint-free","provider","deepseek"),
        ("openrouter-google-gemma4-26b-a4b-free","cost_class","metered-api"),
        ("openrouter-particle-1-free","api_base","https://example.com/v1"),
        ("openrouter-particle-1-free","treatment_kind","router"),
        ("openrouter-particle-1-free","extra_body",{"provider":{"allow_fallbacks":True}}),
    ):
        fixture=copy.deepcopy(base)
        fixture[identifier][field]=bad
        try:assert_binding(fixture,observed)
        except ValueError:count+=1
        else:raise AssertionError("mutant admitted: "+field)
    for malformed in (
        observed[:-1],
        (*observed,"openrouter/free"),
        (*observed,observed[0]),
    ):
        try:assert_binding(base,tuple(malformed))
        except ValueError:count+=1
        else:raise AssertionError("census mutant admitted")
    return count

def main() -> None:
    spec=importlib.util.spec_from_file_location("r11_census",CENSUS)
    assert spec and spec.loader
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed=tuple(module.CANDIDATES)
    catalog=json.loads(CATALOG.read_text())["candidates"]
    assert_binding(catalog,observed)
    negative_cases=test_negatives(catalog,observed)
    workflow=WORKFLOW.read_text()
    required=(
        "workflow_dispatch:",
        "environment: hosted-qualification",
        "secrets.OPENROUTER_API_KEY",
        'QUALIFICATION_BOUNDARY=nonzero-provider-price',
        'QUALIFICATION_BOUNDARY=tool-calling-not-supported',
        'QUALIFICATION_BOUNDARY=OpenRouter-model-not-visible',
    )
    for term in required:
        if term not in workflow:raise AssertionError("hosted boundary absent")
    print(json.dumps({
        "schema":"openrouter-catalog-binding-guard/v1",
        "state":"PASS",
        "paired_exact_models":len(observed),
        "negative_cases":negative_cases,
        "scope":"SOURCE_ONLY_NO_INFERENCE",
    },sort_keys=True))

if __name__=="__main__":
    main()
