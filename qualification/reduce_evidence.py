#!/usr/bin/env python3
"""Deterministically reduce immutable run receipts into task-conditioned evidence envelopes."""

from __future__ import annotations

import argparse
import hashlib
import json
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
    if bool(obs.get("success")):
        return "pass"
    workload = obs.get("workload") or {}
    zero_round_nonterminal = (
        not obs.get("timed_out", False)
        and obs.get("candidate_exit_code") == 0
        and workload.get("model_rounds") == 0
    )
    return "incomplete" if zero_round_nonterminal else "fail"


def reduce_receipts(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    actor_records: dict[str, dict[str, Any]] = {}

    for receipt in receipts:
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
        mapping = KSA_BY_TASK_CLASS.get(task_class, {})
        state = ksa_state(successes, failures)
        ksa = {
            family: {name: state for name in names}
            for family, names in mapping.items()
        }
        envelopes.append(
            {
                "schema_version": 1,
                "actor_realization_id": actor_id,
                "actor": actor_records[actor_id],
                "task_class": task_class,
                "evidence_pattern": evidence_pattern(successes, failures),
                "evidence": {
                    "reps": len(rows),
                    "validated_pass": successes,
                    "validated_fail": failures,
                    "incomplete": incomplete,
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

    rows = [json.loads(path.read_text(encoding="utf-8")) for path in args.receipts]
    result = {"schema_version": 1, "envelopes": reduce_receipts(rows)}
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
