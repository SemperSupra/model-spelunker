#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
from pathlib import Path


SIGNALS = [
    "cache_read_tokens",
    "cache_write_tokens",
    "human_interventions",
    "input_tokens",
    "logical_cpus_visible",
    "memory_total_bytes",
    "model_calls_completed",
    "model_calls_started",
    "output_tokens",
    "platform_machine",
    "platform_system",
    "terminal_state",
    "tool_calls",
    "validator_success",
    "wall_seconds",
]

PURPOSE = {
    "cache_read_tokens": "experimental",
    "cache_write_tokens": "experimental",
    "human_interventions": "both",
    "input_tokens": "experimental",
    "logical_cpus_visible": "both",
    "memory_total_bytes": "both",
    "model_calls_completed": "experimental",
    "model_calls_started": "experimental",
    "output_tokens": "experimental",
    "platform_machine": "both",
    "platform_system": "both",
    "terminal_state": "both",
    "tool_calls": "both",
    "validator_success": "both",
    "wall_seconds": "both",
}

UNITS = {
    "cache_read_tokens": "provider-tokens",
    "cache_write_tokens": "provider-tokens",
    "human_interventions": "count",
    "input_tokens": "provider-tokens",
    "logical_cpus_visible": "count",
    "memory_total_bytes": "bytes",
    "model_calls_completed": "count",
    "model_calls_started": "count",
    "output_tokens": "provider-tokens",
    "platform_machine": None,
    "platform_system": None,
    "terminal_state": None,
    "tool_calls": "count",
    "validator_success": None,
    "wall_seconds": "seconds",
}

SOURCES = {
    "cache_read_tokens": "observation.cache_read_tokens",
    "cache_write_tokens": "observation.cache_write_tokens",
    "human_interventions": "observation.human_interventions",
    "input_tokens": "observation.input_tokens",
    "logical_cpus_visible": "resources.logical_cpus_visible",
    "memory_total_bytes": "resources.memory_total_bytes",
    "model_calls_completed": "observation.workload.model_calls_completed",
    "model_calls_started": "observation.workload.model_calls_started",
    "output_tokens": "observation.output_tokens",
    "platform_machine": "resources.platform_machine",
    "platform_system": "resources.platform_system",
    "terminal_state": "observation.termination_class",
    "tool_calls": "observation.tool_calls",
    "validator_success": "observation.success",
    "wall_seconds": "observation.wall_seconds",
}


def load(root: Path):
    path = root / "telemetry_coverage.py"
    spec = importlib.util.spec_from_file_location("telemetry_coverage_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load telemetry_coverage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "project_coverage", None)
    if not callable(fn):
        raise RuntimeError("project_coverage is not callable")
    return fn


def receipt(*, hosted: bool, zero_usage: bool = False, sparse: bool = False):
    candidate = {
        "configuration_digest": "sha256:" + ("1" if hosted else "2") * 64,
        "model": {
            "provider": "deepseek" if hosted else "mlx-lm",
            "id": "deepseek-flash" if hosted else "qwen-local",
        },
        "deployment_topology": {
            "runtime_placement": "hosted-service" if hosted else "local-service",
            "transport": "provider-api" if hosted else "loopback-http",
            "compute_class": "provider-opaque" if hosted else "gpu",
        },
    }
    obs = {
        "termination_class": "semantic-success",
        "success": True,
        "wall_seconds": 3.25 if hosted else 9.5,
        "tool_calls": 0 if zero_usage else 2,
        "human_interventions": 0,
        "input_tokens": 0 if zero_usage else 111,
        "output_tokens": 0 if zero_usage else 22,
        "cache_read_tokens": 0 if zero_usage else 7,
        "cache_write_tokens": 0 if zero_usage else 3,
        "workload": {
            "model_calls_started": 0 if zero_usage else 3,
            "model_calls_completed": 0 if zero_usage else 3,
        },
    }
    resources = {
        "logical_cpus_visible": 4,
        "memory_total_bytes": None if hosted else 7516192768,
        "platform_system": "Linux" if hosted else "Darwin",
        "platform_machine": "x86_64" if hosted else "arm64",
    }
    if sparse:
        for key in ("input_tokens", "cache_read_tokens"):
            obs.pop(key, None)
        obs["cache_write_tokens"] = None
        obs["workload"].pop("model_calls_completed", None)
        resources.pop("memory_total_bytes", None)
        resources["platform_machine"] = None
    return {
        "schema_version": 2,
        "run_id": "run-hosted" if hosted else "run-local",
        "task": {"id": "fixture-task"},
        "candidate": candidate,
        "observation": obs,
        "resources": resources,
    }


def expected_value(source: str, data: dict):
    cur = data
    for part in source.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def validate_projection(fn, data: dict):
    original = copy.deepcopy(data)
    got = fn(data)
    if data != original:
        raise AssertionError("project_coverage mutated the receipt")
    if not isinstance(got, dict) or set(got) != {"schema_version", "source", "signals"}:
        raise AssertionError("unexpected top-level projection shape")
    if got["schema_version"] != 1:
        raise AssertionError("schema_version must be 1")
    expected_source = {
        "run_id": data["run_id"],
        "task_id": data["task"]["id"],
        "actor_configuration_digest": data["candidate"]["configuration_digest"],
        "model_provider": data["candidate"]["model"]["provider"],
        "model_id": data["candidate"]["model"]["id"],
        "runtime_placement": data["candidate"]["deployment_topology"]["runtime_placement"],
        "transport": data["candidate"]["deployment_topology"]["transport"],
        "compute_class": data["candidate"]["deployment_topology"]["compute_class"],
    }
    if got["source"] != expected_source:
        raise AssertionError("source identity projection mismatch")
    rows = got["signals"]
    if not isinstance(rows, list) or [row.get("signal") for row in rows] != SIGNALS:
        raise AssertionError("signals must be the fixed lexicographic list")
    for row in rows:
        if set(row) != {
            "signal","purpose","availability","evidence_class","value","unit","source"
        }:
            raise AssertionError("unexpected signal row shape")
        signal = row["signal"]
        source = SOURCES[signal]
        value = expected_value(source, data)
        available = value is not None
        if row["source"] != source:
            raise AssertionError(f"bad source for {signal}")
        if row["purpose"] != PURPOSE[signal]:
            raise AssertionError(f"bad purpose for {signal}")
        if row["unit"] != UNITS[signal]:
            raise AssertionError(f"bad unit for {signal}")
        if row["availability"] != ("available" if available else "unknown"):
            raise AssertionError(f"bad availability for {signal}")
        if row["evidence_class"] != ("observed" if available else "unknown"):
            raise AssertionError(f"bad evidence class for {signal}")
        if row["value"] != value:
            raise AssertionError(f"bad value for {signal}")
    rendered = repr(got).lower()
    for forbidden in ("normalized_token", "work_score", "vram", "gpu_model", "provider_gpu"):
        if forbidden in rendered:
            raise AssertionError(f"forbidden inferred/normalized telemetry: {forbidden}")
    return got


def check(root: Path) -> bool:
    try:
        fn = load(root)
        hosted = validate_projection(fn, receipt(hosted=True))
        local = validate_projection(fn, receipt(hosted=False))
        zero = validate_projection(fn, receipt(hosted=True, zero_usage=True))
        sparse = validate_projection(fn, receipt(hosted=True, sparse=True))

        by_signal = {row["signal"]: row for row in zero["signals"]}
        for name in (
            "input_tokens","output_tokens","cache_read_tokens","cache_write_tokens",
            "model_calls_started","model_calls_completed","tool_calls","human_interventions"
        ):
            if by_signal[name]["value"] != 0:
                return False
            if by_signal[name]["availability"] != "available":
                return False
            if by_signal[name]["evidence_class"] != "observed":
                return False

        sparse_rows = {row["signal"]: row for row in sparse["signals"]}
        for name in ("input_tokens","cache_read_tokens","cache_write_tokens","model_calls_completed","memory_total_bytes","platform_machine"):
            if sparse_rows[name]["value"] is not None:
                return False
            if sparse_rows[name]["availability"] != "unknown":
                return False
            if sparse_rows[name]["evidence_class"] != "unknown":
                return False

        # Provider-opaque hosted compute must remain provider-opaque; the projector
        # must not manufacture local accelerator facts.
        if hosted["source"]["compute_class"] != "provider-opaque":
            return False
        if local["source"]["compute_class"] != "gpu":
            return False
        return True
    except Exception:
        return False


def self_test() -> int:
    good = """from __future__ import annotations

PATHS = {
    "cache_read_tokens": ("experimental", "provider-tokens", "observation.cache_read_tokens"),
    "cache_write_tokens": ("experimental", "provider-tokens", "observation.cache_write_tokens"),
    "human_interventions": ("both", "count", "observation.human_interventions"),
    "input_tokens": ("experimental", "provider-tokens", "observation.input_tokens"),
    "logical_cpus_visible": ("both", "count", "resources.logical_cpus_visible"),
    "memory_total_bytes": ("both", "bytes", "resources.memory_total_bytes"),
    "model_calls_completed": ("experimental", "count", "observation.workload.model_calls_completed"),
    "model_calls_started": ("experimental", "count", "observation.workload.model_calls_started"),
    "output_tokens": ("experimental", "provider-tokens", "observation.output_tokens"),
    "platform_machine": ("both", None, "resources.platform_machine"),
    "platform_system": ("both", None, "resources.platform_system"),
    "terminal_state": ("both", None, "observation.termination_class"),
    "tool_calls": ("both", "count", "observation.tool_calls"),
    "validator_success": ("both", None, "observation.success"),
    "wall_seconds": ("both", "seconds", "observation.wall_seconds"),
}
def _get(data, path):
    cur=data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur=cur[part]
    return cur
def project_coverage(receipt: dict) -> dict:
    source={
        "run_id":receipt["run_id"],
        "task_id":receipt["task"]["id"],
        "actor_configuration_digest":receipt["candidate"]["configuration_digest"],
        "model_provider":receipt["candidate"]["model"]["provider"],
        "model_id":receipt["candidate"]["model"]["id"],
        "runtime_placement":receipt["candidate"]["deployment_topology"]["runtime_placement"],
        "transport":receipt["candidate"]["deployment_topology"]["transport"],
        "compute_class":receipt["candidate"]["deployment_topology"]["compute_class"],
    }
    rows=[]
    for signal in sorted(PATHS):
        purpose,unit,path=PATHS[signal]
        value=_get(receipt,path)
        available=value is not None
        rows.append({
            "signal":signal,"purpose":purpose,
            "availability":"available" if available else "unknown",
            "evidence_class":"observed" if available else "unknown",
            "value":value,"unit":unit,"source":path,
        })
    return {"schema_version":1,"source":source,"signals":rows}
"""
    bad = good.replace('available=value is not None', 'available=bool(value)').replace(
        '"compute_class":receipt["candidate"]["deployment_topology"]["compute_class"],',
        '"compute_class":"gpu",'
    )
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        path=root/"telemetry_coverage.py"
        path.write_text(good,encoding="utf-8")
        assert check(root)
        path.write_text(bad,encoding="utf-8")
        assert not check(root)
    print("PASS telemetry coverage verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv)==2 and sys.argv[1]=="--self-test":
        raise SystemExit(self_test())
    if len(sys.argv)!=2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
