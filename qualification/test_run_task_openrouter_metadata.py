#!/usr/bin/env python3
from qualification.run_task import workload_summary

summary = workload_summary([
    {
        "requested_model": "openrouter/free",
        "openrouter_generation": {
            "model": "example/model-free",
            "provider_name": "ExampleProvider",
            "is_byok": False,
            "total_cost": 0.0,
        },
    },
    {
        "requested_model": "openai/gpt-oss-20b",
        "openrouter_generation": {
            "model": "openai/gpt-oss-20b",
            "provider_name": "Groq",
            "is_byok": True,
            "total_cost": 0.0,
        },
    },
    {
        "requested_model": "openrouter/free",
        "openrouter_generation_error": "HTTPError:404",
    },
])

assert summary["resolved_models"] == ["example/model-free", "openai/gpt-oss-20b"]
assert summary["serving_providers"] == ["ExampleProvider", "Groq"]
assert summary["is_byok_values"] == [False, True]
assert summary["provider_metadata_errors"] == ["HTTPError:404"]
assert summary["provider_reported_cost_total"] == 0.0
print("PASS OpenRouter generation provenance projection")
