#!/usr/bin/env python3
"""Deterministically reduce immutable run receipts into task-conditioned evidence envelopes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


# Legacy task-class mappings predate explicit task->KSA evidence roles.
# Preserve them as composite positive evidence only: a legacy task failure does
# not localize the limiting KSA.
KSA_BY_TASK_CLASS = {
    "software.bounded-repair": {
        "skills": ["bounded_change_execution", "governed_file_tool_use"],
        "abilities": ["scope_discipline"],
    },
    "repository.capability-discovery": {
        "skills": ["repository_discovery", "validation_path_identification"],
        "abilities": ["evidence_discrimination", "unknown_preservation"],
    },
    "software.bounded-debugging": {
        "skills": ["fault_localization", "bounded_code_repair"],
        "abilities": ["evidence_discrimination", "scope_discipline"],
    },
    "repository.state-reconciliation": {
        "skills": ["repository_state_reconciliation"],
        "abilities": ["evidence_precedence", "unknown_preservation"],
    },
}


def digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def actor_realization(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate": receipt["candidate"],
        "substrate": receipt["substrate"],
    }


def evidence_pattern(successes: int, failures: int) -> str:
    if successes and failures:
        return "MIXED"
    if successes:
        return "PASS_ONLY"
    if failures:
        return "FAIL_ONLY"
    return "NO_TERMINAL_EVIDENCE"


def terminal_outcome(receipt: dict[str, Any]) -> str:
    obs = receipt["observation"]
    if bool(obs.get("success")):
        return "pass"
    termination = obs.get("termination_class")
    workload = obs.get("workload") or {}
    signals = set(obs.get("failure_signals") or [])
    no_completed_rounds = (
        not obs.get("success", False)
        and workload.get("model_rounds") == 0
    )
    started_calls = workload.get("model_calls_started")
    censor_observed = (
        termination in {"timeout-censored", "iteration-censored"}
        or obs.get("timed_out")
        or "timeout" in signals
        or "iteration-limit" in signals
    )
    if censor_observed and isinstance(started_calls, int) and started_calls > 0:
        return "censored"
    if no_completed_rounds:
        return "incomplete"
    if censor_observed:
        return "censored"
    engine_error = bool(obs.get("engine_error_types")) or "engine-error-event" in signals
    validator_error = "validator-error" in signals or obs.get("failure_class") == "validator-error"
    return "incomplete" if engine_error or validator_error else "fail"


def wilson_interval(
    successes: int, trials: int, z: float = 1.959963984540054
) -> dict[str, float] | None:
    if trials <= 0:
        return None
    p = successes / trials
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = (p + z2 / (2.0 * trials)) / denom
    half = z * math.sqrt(
        (p * (1.0 - p) / trials) + z2 / (4.0 * trials * trials)
    ) / denom
    return {
        "estimate": round(p, 6),
        "lower_95": round(max(0.0, center - half), 6),
        "upper_95": round(min(1.0, center + half), 6),
    }


def legacy_ksa_requirements(task_class: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for family, names in KSA_BY_TASK_CLASS.get(task_class, {}).items():
        for name in names:
            out.append(
                {
                    "family": family,
                    "name": name,
                    "evidence_role": "composite",
                }
            )
    return out


def ksa_requirements(receipt: dict[str, Any], task_class: str) -> list[dict[str, str]]:
    explicit = receipt.get("task", {}).get("ksa_requirements")
    if isinstance(explicit, list) and explicit:
        return [
            {
                "family": str(row["family"]),
                "name": str(row["name"]),
                "evidence_role": str(row["evidence_role"]),
            }
            for row in explicit
            if isinstance(row, dict)
            and row.get("family")
            and row.get("name")
            and row.get("evidence_role")
        ]
    return legacy_ksa_requirements(task_class)


def ksa_state(
    strong_positive: int,
    supporting_positive: int,
    isolating_negative: int,
) -> str:
    if strong_positive >= 1 and isolating_negative >= 1:
        return "MIXED_EVIDENCE"
    if isolating_negative >= 1:
        return "NEGATIVE_BOUNDARY_OBSERVED"
    if strong_positive >= 2:
        return "REPEATED_EVIDENCE"
    if strong_positive >= 1:
        return "OBSERVED"
    if supporting_positive >= 1:
        return "SUPPORTING_EVIDENCE"
    return "INSUFFICIENT_EVIDENCE"


def reduce_ksa_evidence(
    rows: list[dict[str, Any]],
    outcomes: list[str],
    task_class: str,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, dict[str, Any]]]]:
    counters: dict[tuple[str, str], dict[str, Any]] = {}

    for receipt, outcome in zip(rows, outcomes):
        if outcome not in {"pass", "fail"}:
            continue
        for req in ksa_requirements(receipt, task_class):
            key = (req["family"], req["name"])
            counter = counters.setdefault(
                key,
                {
                    "strong_positive": 0,
                    "supporting_positive": 0,
                    "isolating_negative": 0,
                    "nonisolating_task_negative": 0,
                    "roles_observed": set(),
                },
            )
            role = req["evidence_role"]
            counter["roles_observed"].add(role)
            if outcome == "pass":
                if role == "supporting":
                    counter["supporting_positive"] += 1
                else:
                    counter["strong_positive"] += 1
            elif role == "isolating":
                counter["isolating_negative"] += 1
            else:
                counter["nonisolating_task_negative"] += 1

    ksa: dict[str, dict[str, str]] = {}
    detail: dict[str, dict[str, dict[str, Any]]] = {}
    for (family, name), counter in sorted(counters.items()):
        state = ksa_state(
            counter["strong_positive"],
            counter["supporting_positive"],
            counter["isolating_negative"],
        )
        ksa.setdefault(family, {})[name] = state
        detail.setdefault(family, {})[name] = {
            "state": state,
            "strong_positive_trials": counter["strong_positive"],
            "supporting_positive_trials": counter["supporting_positive"],
            "isolating_negative_trials": counter["isolating_negative"],
            "nonisolating_task_negative_trials": counter["nonisolating_task_negative"],
            "roles_observed": sorted(counter["roles_observed"]),
        }
    return ksa, detail


def reduce_receipts(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_runs: dict[str, str] = {}
    for receipt in receipts:
        run_id = receipt["run_id"]
        fingerprint = digest(receipt)
        prior = seen_runs.get(run_id)
        if prior is None:
            seen_runs[run_id] = fingerprint
            deduped.append(receipt)
        elif prior != fingerprint:
            raise ValueError(f"duplicate run_id with divergent receipt: {run_id}")

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    actor_records: dict[str, dict[str, Any]] = {}

    for receipt in deduped:
        actor = actor_realization(receipt)
        actor_id = digest(actor)
        actor_records[actor_id] = actor
        task_class = receipt["task"].get("task_class") or "UNKNOWN"
        groups[(actor_id, task_class)].append(receipt)

    envelopes = []
    for (actor_id, task_class), rows in sorted(groups.items()):
        outcomes = [terminal_outcome(r) for r in rows]
        successes = outcomes.count("pass")
        failures = outcomes.count("fail")
        incomplete = outcomes.count("incomplete")
        censored = outcomes.count("censored")
        semantic_trials = successes + failures
        task_ids = sorted({r["task"]["id"] for r in rows})
        ksa, ksa_detail = reduce_ksa_evidence(rows, outcomes, task_class)

        envelopes.append(
            {
                "schema_version": 2,
                "actor_realization_id": actor_id,
                "actor": actor_records[actor_id],
                "task_class": task_class,
                "evidence_pattern": evidence_pattern(successes, failures),
                "evidence": {
                    "reps": len(rows),
                    "validated_pass": successes,
                    "validated_fail": failures,
                    "incomplete": incomplete,
                    "censored": censored,
                    "semantic_trials": semantic_trials,
                    "success_interval_wilson_95": wilson_interval(
                        successes, semantic_trials
                    ),
                    "unique_task_instances": len(task_ids),
                    "task_ids": task_ids,
                    "run_ids": sorted(r["run_id"] for r in rows),
                },
                "ksa_evidence": ksa,
                "ksa_evidence_detail": ksa_detail,
            }
        )
    return envelopes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipts", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = [json.loads(path.read_text(encoding="utf-8")) for path in args.receipts]
    result = {"schema_version": 2, "envelopes": reduce_receipts(rows)}
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
