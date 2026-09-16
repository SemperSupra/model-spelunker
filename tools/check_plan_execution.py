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


def check(capsule_manifest: Path, result_dir: Path) -> dict[str, Any]:
    manifest = load_json(capsule_manifest)
    receipt_path = result_dir / "execution-receipt.json"
    result_path = result_dir / "result.json"
    study_path = result_dir / "study.json"
    receipt = load_json(receipt_path)
    result = load_json(result_path)

    deviations: list[dict[str, Any]] = []
    planned_files = manifest.get("files", {})
    executed_inputs = receipt.get("inputs", {})

    for name, planned in planned_files.items():
        compare_identity(deviations, f"input:{name}", planned, executed_inputs.get(name))

    # The executed study copy and result bytes must agree with the execution receipt.
    outputs = receipt.get("outputs", {})
    for name, path in (("study.json", study_path), ("result.json", result_path)):
        actual = identity(path) if path.is_file() else None
        compare_identity(deviations, f"output:{name}", outputs.get(name), actual)

    planned_study_sha = planned_files.get("study.json", {}).get("sha256")
    result_study_sha = result.get("study_declaration_sha256")
    if planned_study_sha != result_study_sha:
        deviations.append({
            "subject": "result:study_declaration_sha256",
            "planned": planned_study_sha,
            "actual": result_study_sha,
        })

    return {
        "schema_version": 1,
        "record_type": "plan-execution-check",
        "status": "MATCH" if not deviations else "DEVIATION",
        "capsule_sha256": manifest.get("capsule_sha256"),
        "study_id": result.get("study_id"),
        "execution_disposition": result.get("execution_disposition"),
        "scientific_disposition": result.get("scientific_disposition"),
        "deviations": deviations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare a sealed pre-execution capsule manifest with one executed result bundle."
    )
    parser.add_argument("capsule_manifest", type=Path)
    parser.add_argument("result_dir", type=Path)
    args = parser.parse_args()
    report = check(args.capsule_manifest, args.result_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
