#!/usr/bin/env python3
"""Compare two qualification receipts for venue-portability invariants.

This is intentionally narrower than qualification itself. It asks whether moving
an otherwise identical contract rep between execution venues changes anything
that should be venue-invariant.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def fail(message: str) -> None:
    raise ValueError(message)


def compare(native: dict[str, Any], alternate: dict[str, Any]) -> dict[str, Any]:
    if native.get("schema_version") != alternate.get("schema_version"):
        fail("schema_version drift")

    for field in ("task", "candidate", "evidence_digest"):
        if native.get(field) != alternate.get(field):
            fail(f"{field} drift")

    nobs = native["observation"]
    aobs = alternate["observation"]
    invariant_observation_fields = (
        "success",
        "failure_class",
        "human_interventions",
        "candidate_exit_code",
        "verifier_exit_code",
        "timed_out",
        "state_changed",
        "failure_signals",
        "engine_error_types",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "workload",
        "cost",
    )
    for field in invariant_observation_fields:
        if nobs.get(field) != aobs.get(field):
            fail(f"observation.{field} drift")

    if native["run_id"] == alternate["run_id"]:
        fail("independent reps reused run_id")

    if native["substrate"]["profile_id"] == alternate["substrate"]["profile_id"]:
        fail("portable rehearsal must use distinct substrate profile ids")

    if native["substrate"]["profile_commit"] != alternate["substrate"]["profile_commit"]:
        fail("substrate profile revision drift")

    return {
        "schema_version": 1,
        "result": "PASS",
        "task_id": native["task"]["id"],
        "task_package_digest": native["task"]["package_digest"],
        "candidate_configuration_digest": native["candidate"]["configuration_digest"],
        "evidence_digest": native["evidence_digest"],
        "native_substrate": native["substrate"],
        "alternate_substrate": alternate["substrate"],
        "native_run_id": native["run_id"],
        "alternate_run_id": alternate["run_id"],
        "allowed_variance": {
            "run_id": True,
            "wall_seconds": True,
            "substrate_profile_id": True,
        },
    }



def compare_structural(native: dict[str, Any], alternate: dict[str, Any]) -> dict[str, Any]:
    """Compare stochastic actor reps without pretending their traces are byte-identical."""
    if native.get("schema_version") != alternate.get("schema_version"):
        fail("schema_version drift")

    ntask=native["task"]
    atask=alternate["task"]
    for field in ("id","task_class","package_digest"):
        if ntask.get(field)!=atask.get(field):
            fail(f"task.{field} drift")

    if native.get("candidate") != alternate.get("candidate"):
        fail("candidate drift")

    nobs=native["observation"]
    aobs=alternate["observation"]
    structural_fields=(
        "success",
        "failure_class",
        "timed_out",
        "state_changed",
        "failure_signals",
        "engine_error_types",
    )
    observed_differences={
        field:{"native":nobs.get(field),"alternate":aobs.get(field)}
        for field in structural_fields
        if nobs.get(field)!=aobs.get(field)
    }
    return {
        "schema_version":1,
        "mode":"stochastic-structural",
        "identity_match":True,
        "structural_outcome_match":not observed_differences,
        "task_id":ntask["id"],
        "task_package_digest":ntask["package_digest"],
        "candidate_configuration_digest":native["candidate"]["configuration_digest"],
        "native_substrate":native["substrate"],
        "alternate_substrate":alternate["substrate"],
        "observed_differences":observed_differences,
        "notes":[
            "Token counts, wall time, model rounds, tool counts, and output traces are observations rather than equality gates.",
            "A structural outcome difference is experiment evidence; it is not automatically a methodology failure.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("native", type=Path)
    parser.add_argument("alternate", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", choices=["deterministic","stochastic-structural"], default="deterministic")
    args = parser.parse_args()

    native = json.loads(args.native.read_text(encoding="utf-8"))
    alternate = json.loads(args.alternate.read_text(encoding="utf-8"))
    result = (
        compare(native, alternate)
        if args.mode == "deterministic"
        else compare_structural(native, alternate)
    )
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
