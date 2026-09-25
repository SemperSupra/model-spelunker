#!/usr/bin/env python3
from __future__ import annotations

import copy

from qualification.telemetry_coverage import project_coverage


def fixture(*, sparse=False, zero=False):
    obs = {
        "termination_class": "semantic-success",
        "success": True,
        "wall_seconds": 1.25,
        "tool_calls": 0 if zero else 2,
        "human_interventions": 0,
        "input_tokens": 0 if zero else 10,
        "output_tokens": 0 if zero else 3,
        "cache_read_tokens": 0 if zero else 2,
        "cache_write_tokens": 0 if zero else 1,
        "workload": {
            "model_calls_started": 0 if zero else 2,
            "model_calls_completed": 0 if zero else 2,
        },
    }
    resources = {
        "logical_cpus_visible": 4,
        "memory_total_bytes": None if sparse else 16_000_000_000,
        "platform_system": "Linux",
        "platform_machine": None if sparse else "x86_64",
    }
    if sparse:
        obs.pop("input_tokens")
        obs["cache_read_tokens"] = None
        obs["workload"].pop("model_calls_completed")
    return {
        "schema_version": 2,
        "run_id": "fixture-run",
        "task": {"id": "fixture-task"},
        "candidate": {
            "configuration_digest": "sha256:" + "a" * 64,
            "model": {"provider": "deepseek", "id": "deepseek-flash"},
            "deployment_topology": {
                "runtime_placement": "hosted-service",
                "transport": "provider-api",
                "compute_class": "provider-opaque",
            },
        },
        "observation": obs,
        "resources": resources,
    }


source = fixture()
original = copy.deepcopy(source)
projection = project_coverage(source)
assert source == original
assert projection["schema_version"] == 1
assert projection["source"]["compute_class"] == "provider-opaque"

signals = projection["signals"]
names = [row["signal"] for row in signals]
assert names == sorted(names)
assert len(names) == 15
assert len(set(names)) == 15

zero = {row["signal"]: row for row in project_coverage(fixture(zero=True))["signals"]}
for name in (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "model_calls_started",
    "model_calls_completed",
    "tool_calls",
    "human_interventions",
):
    assert zero[name]["value"] == 0
    assert zero[name]["availability"] == "available"
    assert zero[name]["evidence_class"] == "observed"

sparse = {row["signal"]: row for row in project_coverage(fixture(sparse=True))["signals"]}
for name in ("input_tokens", "cache_read_tokens", "model_calls_completed", "memory_total_bytes", "platform_machine"):
    assert sparse[name]["value"] is None
    assert sparse[name]["availability"] == "unknown"
    assert sparse[name]["evidence_class"] == "unknown"

print("PASS telemetry coverage product contract")
