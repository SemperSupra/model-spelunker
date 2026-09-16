#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def identity(path: Path) -> dict[str, object]:
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def compare_identity(
    deviations: list[dict[str, Any]],
    subject: str,
    planned: dict[str, Any] | None,
    actual: dict[str, Any] | None,
) -> None:
    if planned is None or actual is None:
        deviations.append({"subject": subject, "planned": planned, "actual": actual})
        return
    if planned.get("sha256") != actual.get("sha256") or planned.get("bytes") != actual.get("bytes"):
        deviations.append({"subject": subject, "planned": planned, "actual": actual})


def compare_value(
    deviations: list[dict[str, Any]],
    subject: str,
    planned: Any,
    actual: Any,
) -> None:
    if planned != actual:
        deviations.append({"subject": subject, "planned": planned, "actual": actual})


def result_layout(result_dir: Path) -> tuple[Path, Path]:
    """Return (transport root, project files directory)."""
    if (result_dir / "execution.json").is_file():
        project_dir = result_dir / "files" if (result_dir / "files").is_dir() else result_dir
        return result_dir, project_dir
    if result_dir.name == "files" and (result_dir.parent / "execution.json").is_file():
        return result_dir.parent, result_dir
    return result_dir, result_dir


def check(capsule_manifest: Path, result_dir: Path) -> dict[str, Any]:
    manifest = load_json(capsule_manifest)
    transport_dir, project_dir = result_layout(result_dir)
    execution_path = transport_dir / "execution.json"
    receipt_path = project_dir / "execution-receipt.json"
    result_path = project_dir / "result.json"
    plan_name = str(manifest.get("plan_file") or "study.json")
    plan_path = project_dir / plan_name

    deviations: list[dict[str, Any]] = []
    planned_files = manifest.get("files", {})

    execution: dict[str, Any] = {}
    if execution_path.is_file():
        execution = load_json(execution_path)
    else:
        deviations.append({"subject": "execution.json", "planned": "present", "actual": "missing"})

    receipt: dict[str, Any] = {}
    if receipt_path.is_file():
        receipt = load_json(receipt_path)
    else:
        deviations.append({"subject": "execution-receipt.json", "planned": "present", "actual": "missing"})

    result: dict[str, Any] = {}
    if result_path.is_file():
        result = load_json(result_path)
    else:
        deviations.append({"subject": "result.json", "planned": "present", "actual": "missing"})

    compare_value(
        deviations,
        "execution:capsule_sha256",
        manifest.get("capsule_sha256"),
        execution.get("capsule_sha256"),
    )

    executed_inputs = receipt.get("inputs", {})
    for name, planned in planned_files.items():
        compare_identity(deviations, f"input:{name}", planned, executed_inputs.get(name))

    outputs = receipt.get("outputs", {})
    for name, path in ((plan_name, plan_path), ("result.json", result_path)):
        actual = identity(path) if path.is_file() else None
        compare_identity(deviations, f"output:{name}", outputs.get(name), actual)

    planned_plan_sha = planned_files.get(plan_name, {}).get("sha256")
    result_plan_sha = result.get("plan_sha256")
    if result_plan_sha is None and plan_name == "study.json":
        result_plan_sha = result.get("study_declaration_sha256")
    compare_value(
        deviations,
        "result:plan_sha256",
        planned_plan_sha,
        result_plan_sha,
    )

    compare_value(
        deviations,
        "execution:task_exit_code",
        receipt.get("task_exit_code"),
        execution.get("task_exit_code"),
    )

    return {
        "schema_version": 1,
        "record_type": "plan-execution-check",
        "status": "MATCH" if not deviations else "DEVIATION",
        "capsule_sha256": manifest.get("capsule_sha256"),
        "plan_file": plan_name,
        "study_id": result.get("study_id"),
        "qualification_id": result.get("qualification_id"),
        "run_id": execution.get("run_id"),
        "worker_revision": execution.get("worker_revision"),
        "task_exit_code": receipt.get("task_exit_code"),
        "execution_disposition": result.get("execution_disposition"),
        "scientific_disposition": result.get("scientific_disposition"),
        "deviations": deviations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare a sealed pre-execution capsule manifest with one decrypted Agent Dispatch result."
    )
    parser.add_argument("capsule_manifest", type=Path)
    parser.add_argument("result_dir", type=Path)
    args = parser.parse_args()
    report = check(args.capsule_manifest, args.result_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
