#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import math
import sys
import tempfile
from pathlib import Path


EXPECTED_KEYS = {"kind", "value", "unit", "source"}


def load(root: Path):
    path = root / "telemetry_usage.py"
    spec = importlib.util.spec_from_file_location("telemetry_usage_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load telemetry_usage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.project_usage


def full_receipt():
    return {
        "schema_version": 2,
        "observation": {
            "wall_seconds": 12.5,
            "input_tokens": 101,
            "output_tokens": 0,
            "cache_read_tokens": 44,
            "cache_write_tokens": 0,
            "cost": 0.0,
            "human_interventions": 0,
            "workload": {
                "model_calls_started": 3,
                "model_calls_completed": 2,
                "tool_calls_started": 4,
                "tool_calls_completed": 3,
                "client_wall_seconds_total": 9.75,
                "request_message_bytes_total": 1200,
                "request_tool_schema_bytes_total": 400,
                "output_text_bytes_total": 222,
                "reasoning_bytes_total": 0,
                "tool_argument_bytes_total": 88,
            },
            "ignored_metric": 999,
        },
        "candidate": {"model": {"provider": "fixture", "id": "fixture"}},
        "ignored": {"anything": True},
    }


def expected_full():
    return [
        {"kind": "elapsed-time", "value": 12.5, "unit": "seconds", "source": "observed"},
        {"kind": "model-calls-started", "value": 3, "unit": "calls", "source": "observed"},
        {"kind": "model-calls-completed", "value": 2, "unit": "calls", "source": "observed"},
        {"kind": "tool-calls-started", "value": 4, "unit": "calls", "source": "observed"},
        {"kind": "tool-calls-completed", "value": 3, "unit": "calls", "source": "observed"},
        {"kind": "input-tokens", "value": 101, "unit": "tokens", "source": "authoritative"},
        {"kind": "output-tokens", "value": 0, "unit": "tokens", "source": "authoritative"},
        {"kind": "cache-read-tokens", "value": 44, "unit": "tokens", "source": "authoritative"},
        {"kind": "cache-write-tokens", "value": 0, "unit": "tokens", "source": "authoritative"},
        {"kind": "cost", "value": 0.0, "unit": "usd", "source": "authoritative"},
        {"kind": "human-interventions", "value": 0, "unit": "count", "source": "observed"},
        {"kind": "model-client-wall-time", "value": 9.75, "unit": "seconds", "source": "observed"},
        {"kind": "request-message-bytes", "value": 1200, "unit": "bytes", "source": "derived"},
        {"kind": "request-tool-schema-bytes", "value": 400, "unit": "bytes", "source": "derived"},
        {"kind": "output-text-bytes", "value": 222, "unit": "bytes", "source": "derived"},
        {"kind": "reasoning-bytes", "value": 0, "unit": "bytes", "source": "derived"},
        {"kind": "tool-argument-bytes", "value": 88, "unit": "bytes", "source": "derived"},
    ]


def check(root: Path) -> bool:
    try:
        fn = load(root)

        receipt = full_receipt()
        original = copy.deepcopy(receipt)
        got = fn(receipt)
        if receipt != original:
            return False
        if got != expected_full():
            return False
        if any(set(row) != EXPECTED_KEYS for row in got):
            return False

        partial = {
            "observation": {
                "wall_seconds": 0,
                "input_tokens": None,
                "output_tokens": 7,
                "workload": {},
            }
        }
        if fn(partial) != [
            {"kind": "elapsed-time", "value": 0, "unit": "seconds", "source": "observed"},
            {"kind": "output-tokens", "value": 7, "unit": "tokens", "source": "authoritative"},
        ]:
            return False

        invalid = {
            "observation": {
                "wall_seconds": True,
                "input_tokens": -1,
                "output_tokens": "7",
                "cache_read_tokens": float("nan"),
                "cache_write_tokens": float("inf"),
                "cost": -0.01,
                "human_interventions": False,
                "workload": {
                    "model_calls_started": -2,
                    "model_calls_completed": 1,
                    "tool_calls_started": None,
                    "tool_calls_completed": 0,
                    "client_wall_seconds_total": float("-inf"),
                    "request_message_bytes_total": 5,
                },
            }
        }
        if fn(invalid) != [
            {"kind": "model-calls-completed", "value": 1, "unit": "calls", "source": "observed"},
            {"kind": "tool-calls-completed", "value": 0, "unit": "calls", "source": "observed"},
            {"kind": "request-message-bytes", "value": 5, "unit": "bytes", "source": "derived"},
        ]:
            return False

        if fn({}) != []:
            return False
        if fn({"observation": None}) != []:
            return False
        return True
    except Exception:
        return False


def self_test() -> int:
    good = '''"""fixture good implementation"""
import math

MAP = [
    (("observation", "wall_seconds"), "elapsed-time", "seconds", "observed"),
    (("observation", "workload", "model_calls_started"), "model-calls-started", "calls", "observed"),
    (("observation", "workload", "model_calls_completed"), "model-calls-completed", "calls", "observed"),
    (("observation", "workload", "tool_calls_started"), "tool-calls-started", "calls", "observed"),
    (("observation", "workload", "tool_calls_completed"), "tool-calls-completed", "calls", "observed"),
    (("observation", "input_tokens"), "input-tokens", "tokens", "authoritative"),
    (("observation", "output_tokens"), "output-tokens", "tokens", "authoritative"),
    (("observation", "cache_read_tokens"), "cache-read-tokens", "tokens", "authoritative"),
    (("observation", "cache_write_tokens"), "cache-write-tokens", "tokens", "authoritative"),
    (("observation", "cost"), "cost", "usd", "authoritative"),
    (("observation", "human_interventions"), "human-interventions", "count", "observed"),
    (("observation", "workload", "client_wall_seconds_total"), "model-client-wall-time", "seconds", "observed"),
    (("observation", "workload", "request_message_bytes_total"), "request-message-bytes", "bytes", "derived"),
    (("observation", "workload", "request_tool_schema_bytes_total"), "request-tool-schema-bytes", "bytes", "derived"),
    (("observation", "workload", "output_text_bytes_total"), "output-text-bytes", "bytes", "derived"),
    (("observation", "workload", "reasoning_bytes_total"), "reasoning-bytes", "bytes", "derived"),
    (("observation", "workload", "tool_argument_bytes_total"), "tool-argument-bytes", "bytes", "derived"),
]

def _get(obj, path):
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur

def project_usage(receipt):
    out = []
    for path, kind, unit, source in MAP:
        value = _get(receipt, path)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not math.isfinite(value) or value < 0:
            continue
        out.append({"kind":kind,"value":value,"unit":unit,"source":source})
    return out
'''
    bad = '''def project_usage(receipt):
    return [{"kind":"input-tokens","value":0,"unit":"tokens","source":"authoritative"}]
'''
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "telemetry_usage.py"
        path.write_text(good, encoding="utf-8")
        assert check(root)
        path.write_text(bad, encoding="utf-8")
        assert not check(root)
    print("PASS telemetry usage verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
