from __future__ import annotations

_MISSING = object()


def _get(receipt: dict, path: str):
    """Navigate a dotted path. Return _MISSING if any segment is absent."""
    node = receipt
    for segment in path.split("."):
        if isinstance(node, dict) and segment in node:
            node = node[segment]
        else:
            return _MISSING
    return node


def _signal_row(signal: str, purpose: str, unit, path: str, receipt: dict) -> dict:
    raw = _get(receipt, path)
    if raw is _MISSING or raw is None:
        return {
            "signal": signal,
            "purpose": purpose,
            "availability": "unknown",
            "evidence_class": "unknown",
            "value": None,
            "unit": unit,
            "source": path,
        }
    return {
        "signal": signal,
        "purpose": purpose,
        "availability": "available",
        "evidence_class": "observed",
        "value": raw,
        "unit": unit,
        "source": path,
    }


# signal -> (purpose, source path, unit)
_SIGNAL_SPECS = {
    "cache_read_tokens": ("experimental", "observation.cache_read_tokens", "provider-tokens"),
    "cache_write_tokens": ("experimental", "observation.cache_write_tokens", "provider-tokens"),
    "human_interventions": ("both", "observation.human_interventions", "count"),
    "input_tokens": ("experimental", "observation.input_tokens", "provider-tokens"),
    "logical_cpus_visible": ("both", "resources.logical_cpus_visible", "count"),
    "memory_total_bytes": ("both", "resources.memory_total_bytes", "bytes"),
    "model_calls_completed": ("experimental", "observation.workload.model_calls_completed", "count"),
    "model_calls_started": ("experimental", "observation.workload.model_calls_started", "count"),
    "output_tokens": ("experimental", "observation.output_tokens", "provider-tokens"),
    "platform_machine": ("both", "resources.platform_machine", None),
    "platform_system": ("both", "resources.platform_system", None),
    "terminal_state": ("both", "observation.termination_class", None),
    "tool_calls": ("both", "observation.tool_calls", "count"),
    "validator_success": ("both", "observation.success", None),
    "wall_seconds": ("both", "observation.wall_seconds", "seconds"),
}


def project_coverage(receipt: dict) -> dict:
    """Project existing v2 receipt facts into a compact telemetry coverage profile."""
    source = {
        "run_id": _get(receipt, "run_id"),
        "task_id": _get(receipt, "task.id"),
        "actor_configuration_digest": _get(receipt, "candidate.configuration_digest"),
        "model_provider": _get(receipt, "candidate.model.provider"),
        "model_id": _get(receipt, "candidate.model.id"),
        "runtime_placement": _get(receipt, "candidate.deployment_topology.runtime_placement"),
        "transport": _get(receipt, "candidate.deployment_topology.transport"),
        "compute_class": _get(receipt, "candidate.deployment_topology.compute_class"),
    }
    source = {k: (None if v is _MISSING else v) for k, v in source.items()}

    signals = [
        _signal_row(signal, purpose, unit, path, receipt)
        for signal, (purpose, path, unit) in sorted(_SIGNAL_SPECS.items())
    ]

    return {
        "schema_version": 1,
        "source": source,
        "signals": signals,
    }
