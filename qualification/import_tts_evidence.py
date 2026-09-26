#!/usr/bin/env python3
"""Bind modality-specific TTS evidence into the common v2 qualification receipt.

This is a thin evidence adapter, not a TTS-specific qualification framework.
Audio semantics remain in the digest-bound extension sidecar; the common receipt
carries only configured-actor/task/substrate identity and common outcome/resource
facts needed by the shared reducer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_json_digest(value: object) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def tree_digest(root: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        hasher.update(relative)
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return "sha256:" + hasher.hexdigest()


def _non_null(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def candidate_from_actor(actor: dict[str, Any]) -> dict[str, Any]:
    harness = _non_null(dict(actor["harness"]))
    model = _non_null(dict(actor["model"]))
    candidate: dict[str, Any] = {
        "harness": harness,
        "model": model,
        "toolset": list(actor.get("toolset") or []),
    }
    if isinstance(actor.get("deployment_topology"), dict):
        candidate["deployment_topology"] = dict(actor["deployment_topology"])
    if isinstance(actor.get("configuration"), dict):
        candidate["configuration"] = dict(actor["configuration"])

    identity = dict(candidate)
    candidate["configuration_digest"] = canonical_json_digest(identity)
    return candidate


def receipt_from_tts(
    *,
    task_dir: Path,
    actor_path: Path,
    experiment_path: Path,
    result_path: Path,
    task_source_commit: str,
    substrate_profile_commit: str,
    run_id: str,
) -> dict[str, Any]:
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    actor = json.loads(actor_path.read_text(encoding="utf-8"))
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))

    if task.get("schema_version") != 2:
        raise ValueError("TTS task must use schema_version=2")
    if actor.get("schema_version") != 2:
        raise ValueError("TTS actor must use schema_version=2")
    if experiment.get("schema_version") != 2:
        raise ValueError("TTS experiment must use schema_version=2")
    if experiment["task"]["id"] != task["id"]:
        raise ValueError("experiment/task id mismatch")
    if experiment["actors"] != [actor["id"]]:
        raise ValueError("experiment/actor binding mismatch")
    if result.get("task_id") != task["id"]:
        raise ValueError("result/task id mismatch")
    if result.get("actor_id") != actor["id"]:
        raise ValueError("result/actor id mismatch")
    if result.get("experiment_id") != experiment["id"]:
        raise ValueError("result/experiment id mismatch")

    generation = result.get("generation") or {}
    validation = result.get("validation") or {}
    environment = generation.get("environment") or {}
    success = bool(result.get("success"))
    generation_exit = generation.get("generator_exit_code")
    if not isinstance(generation_exit, int):
        generation_exit = 0 if generation.get("status") == "generated" else 1
    verifier_exit = 0 if bool(validation.get("success")) else 1

    evidence_digest = canonical_json_digest(result)
    execution = actor["execution_environment"]
    receipt: dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_id,
        "task": {
            "id": task["id"],
            "task_class": task.get("task_class"),
            "source_commit": task_source_commit,
            "package_digest": tree_digest(task_dir),
            **(
                {"ksa_requirements": task["ksa_requirements"]}
                if task.get("ksa_requirements")
                else {}
            ),
        },
        "candidate": candidate_from_actor(actor),
        "substrate": {
            "profile_id": execution["substrate_profile"],
            "profile_commit": substrate_profile_commit,
        },
        "observation": {
            "success": success,
            "failure_class": None if success else "tts-content-failure",
            "wall_seconds": float(generation.get("generation_wall_seconds") or 0.0),
            "human_interventions": 0,
            "candidate_exit_code": generation_exit,
            "verifier_exit_code": verifier_exit,
            "tool_calls": None,
            "input_tokens": None,
            "output_tokens": None,
            "cost": None,
            "timed_out": False,
            "state_changed": bool(generation.get("output")),
            "failure_signals": [],
            "cache_read_tokens": None,
            "cache_write_tokens": None,
            "engine_error_types": [],
            "termination_class": (
                "semantic-success" if success else "semantic-failure"
            ),
        },
        "evidence_digest": evidence_digest,
        "experiment": {
            "id": experiment["id"],
            "digest": canonical_json_digest(experiment),
            "claim_type": experiment["claim_type"],
            "experimental_role": experiment["experimental_role"],
            "design_block": experiment.get("design_block"),
            "primary_responses": list(experiment["primary_responses"]),
        },
        "resources": {
            "logical_cpus_visible": None,
            "cpu_model": None,
            "memory_total_bytes": None,
            "cpu_quota_cores": None,
            "cpuset_cpus_effective": None,
            "platform_system": environment.get("platform_system"),
            "platform_machine": environment.get("platform_machine"),
        },
        "extensions": [
            {
                "kind": "audio.tts-generation-validation",
                "schema_version": int(result.get("schema_version") or 1),
                "digest": evidence_digest,
                "ref": result_path.as_posix(),
            }
        ],
        "execution_limits": {
            "wall_seconds": int(task["limits"]["wall_seconds"]),
            "wall_seconds_source": "task",
        },
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--actor", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--task-source-commit", required=True)
    parser.add_argument("--substrate-profile-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    receipt = receipt_from_tts(
        task_dir=args.task_dir,
        actor_path=args.actor,
        experiment_path=args.experiment,
        result_path=args.result,
        task_source_commit=args.task_source_commit,
        substrate_profile_commit=args.substrate_profile_commit,
        run_id=args.run_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
