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


def evidence_pattern(successes: int, failures: int, censored: int = 0) -> str:
    if successes and (failures or censored):
        return "MIXED"
    if successes:
        return "PASS_ONLY"
    if failures or censored:
        return "FAIL_ONLY"
    return "NO_TERMINAL_EVIDENCE"


def ksa_state(successes: int, failures: int) -> str:
    if successes >= 2 and failures == 0:
        return "REPEATED_EVIDENCE"
    if successes >= 1 and failures == 0:
        return "OBSERVED"
    if successes >= 1:
        return "MIXED_EVIDENCE"
    if failures >= 1:
        return "NEGATIVE_BOUNDARY_OBSERVED"
    return "INSUFFICIENT_EVIDENCE"


def terminal_outcome(receipt: dict[str, Any]) -> str:
    obs = receipt["observation"]

    # Admitted completion requires both valid artifact and candidate completion within budget
    admitted = obs.get("admitted_completion")
    if admitted is True:
        return "pass"
    if admitted is False and "admitted_completion" in obs:
        pass
    elif bool(obs.get("success")) and obs.get("candidate_exit_code") == 0 and not obs.get("timed_out"):
        return "pass"

    signals = set(obs.get("failure_signals") or [])
    termination = obs.get("termination_class")

    # Timeout / censorship check: always classified as censored
    if obs.get("timed_out") or termination == "timeout-censored" or "timeout" in signals:
        return "censored"

    # Validator crash (exit not in {0, 1}) or harness engine failure: classified as incomplete
    engine_error = bool(obs.get("engine_error_types")) or "engine-error-event" in signals
    verifier_exit = obs.get("verifier_exit_code")
    validator_error = (
        "validator-error" in signals
        or obs.get("failure_class") == "validator-error"
        or (verifier_exit is not None and verifier_exit not in {0, 1})
    )
    if engine_error or validator_error:
        return "incomplete"

    # All other outcomes (false completion, protocol error, nonzero exit, test fail) are operational failures
    return "fail"


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> dict[str, float] | None:
    if trials <= 0:
        return None
    p = successes / trials
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = (p + z2 / (2.0 * trials)) / denom
    half = z * math.sqrt((p * (1.0 - p) / trials) + z2 / (4.0 * trials * trials)) / denom
    return {
        "estimate": round(p, 6),
        "lower_95": round(max(0.0, center - half), 6),
        "upper_95": round(min(1.0, center + half), 6),
    }


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
        reps = len(rows)
        successes = outcomes.count("pass")
        failures = outcomes.count("fail")
        incomplete = outcomes.count("incomplete")
        censored = outcomes.count("censored")

        # Operational estimand: across all attempted trials
        operational_interval = wilson_interval(successes, reps)

        # Attribute failure types
        protocol_failures = 0
        turn_budget_failures = 0
        for r, out in zip(rows, outcomes):
            if out == "fail":
                harness = (r.get("candidate", {}).get("harness", {}) or {}).get("name")
                stdout = ""
                # Check diagnostics or failure signals
                signals = set(r.get("observation", {}).get("failure_signals") or [])
                if harness == "aider":
                    protocol_failures += 1
                elif harness == "goose" and "false-completion" in signals:
                    turn_budget_failures += 1

        semantic_failures = max(0, failures - protocol_failures)
        semantic_evaluations = successes + semantic_failures

        # Conditional semantic estimand: evaluated only when fair semantic opportunity existed
        conditional_interval = wilson_interval(successes, semantic_evaluations) if semantic_evaluations > 0 else None
        conditional_status = "ESTIMABLE" if semantic_evaluations > 0 else "NOT_ESTIMABLE"

        semantic_trials = successes + failures
        task_ids = sorted({r["task"]["id"] for r in rows})
        mapping = KSA_BY_TASK_CLASS.get(task_class, {})
        state = ksa_state(successes, failures)
        ksa = {
            family: {name: state for name in names}
            for family, names in mapping.items()
        }
        envelopes.append(
            {
                "schema_version": 2,
                "actor_realization_id": actor_id,
                "actor": actor_records[actor_id],
                "task_class": task_class,
                "evidence_pattern": evidence_pattern(successes, failures, censored=censored),
                "evidence": {
                    "reps": reps,
                    "validated_pass": successes,
                    "validated_fail": failures,
                    "incomplete": incomplete,
                    "censored": censored,
                    "operational_success_rate": {
                        "passes": successes,
                        "trials": reps,
                        "wilson_95": operational_interval,
                    },
                    "conditional_semantic_rate": {
                        "passes": successes,
                        "evaluations": semantic_evaluations,
                        "status": conditional_status,
                        "wilson_95": conditional_interval,
                    },
                    "failure_taxonomy": {
                        "protocol_failures": protocol_failures,
                        "turn_budget_failures": turn_budget_failures,
                        "semantic_failures": semantic_failures,
                        "timeout_censored": censored,
                        "validator_invalid": incomplete,
                    },
                    "semantic_trials": semantic_trials,
                    "success_interval_wilson_95": operational_interval,
                    "unique_task_instances": len(task_ids),
                    "task_ids": task_ids,
                    "run_ids": sorted(r["run_id"] for r in rows),
                },
                "ksa_evidence": ksa,
            }
        )
    return envelopes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipts", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    raw_paths: list[Path] = []
    for p in args.receipts:
        s = str(p)
        if "*" in s or "?" in s:
            import glob
            expanded = glob.glob(s)
            raw_paths.extend(Path(x) for x in expanded)
        else:
            raw_paths.append(p)

    # Only include raw run receipts (exclude prior reductions)
    rows = []
    for path in raw_paths:
        if "reduction" in path.name or path.name.endswith(".diag.json"):
            continue
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    result = {"schema_version": 2, "envelopes": reduce_receipts(rows)}
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
