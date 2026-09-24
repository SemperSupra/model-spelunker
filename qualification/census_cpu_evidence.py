#!/usr/bin/env python3
"""Census canonical local-CPU qualification receipts without upgrading their claims."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qualification.reduce_evidence import terminal_outcome


def is_run_receipt(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("run_id"), str)
        and isinstance(value.get("task"), dict)
        and isinstance(value.get("candidate"), dict)
        and isinstance(value.get("substrate"), dict)
        and isinstance(value.get("observation"), dict)
    )


def is_local_cpu_receipt(receipt: dict) -> bool:
    candidate = receipt.get("candidate") or {}
    model = candidate.get("model") or {}
    substrate = receipt.get("substrate") or {}
    provider = str(model.get("provider") or "").lower()
    profile = str(substrate.get("profile_id") or "").lower()
    # Current canonical public-CPU actor receipts use local Ollama. Do not infer
    # hosted-provider CPU internals that are outside our observation boundary.
    return provider == "ollama" or ("cpu" in profile and provider in {"local", "llama.cpp"})


def row(path: Path, receipt: dict) -> dict:
    obs = receipt["observation"]
    workload = obs.get("workload") or {}
    candidate = receipt["candidate"]
    return {
        "source": path.as_posix(),
        "run_id": receipt["run_id"],
        "schema_version": receipt.get("schema_version"),
        "task_id": receipt["task"].get("id"),
        "task_class": receipt["task"].get("task_class"),
        "harness": (candidate.get("harness") or {}).get("name"),
        "harness_version": (candidate.get("harness") or {}).get("version"),
        "model_provider": (candidate.get("model") or {}).get("provider"),
        "model_id": (candidate.get("model") or {}).get("id"),
        "configuration_digest": candidate.get("configuration_digest"),
        "substrate_profile": receipt["substrate"].get("profile_id"),
        "outcome": terminal_outcome(receipt),
        "success": bool(obs.get("success")),
        "wall_seconds": obs.get("wall_seconds"),
        "model_rounds": workload.get("model_rounds"),
        "input_tokens": obs.get("input_tokens"),
        "output_tokens": obs.get("output_tokens"),
        "experiment_id": (receipt.get("experiment") or {}).get("id"),
        "experimental_role": (receipt.get("experiment") or {}).get("experimental_role"),
    }


def census(root: Path) -> dict:
    rows = []
    scanned = 0
    receipts = 0
    historical_design_points = 0
    historical_index_files: list[str] = []
    skipped_invalid_json = []
    for path in sorted(root.glob("*.json")):
        scanned += 1
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            skipped_invalid_json.append(path.as_posix())
            continue
        if not is_run_receipt(value):
            if isinstance(value, dict) and isinstance(value.get("observations"), list) and "historical design points" in str(value.get("purpose") or "").lower():
                historical_design_points += len(value["observations"])
                historical_index_files.append(path.as_posix())
            continue
        receipts += 1
        if is_local_cpu_receipt(value):
            rows.append(row(path, value))
    return {
        "schema_version": 1,
        "scope": "canonical repository run receipts with directly observed local CPU inference route",
        "files_scanned": scanned,
        "run_receipts_found": receipts,
        "local_cpu_receipts": len(rows),
        "historical_design_points_indexed": historical_design_points,
        "historical_index_files": historical_index_files,
        "rows": rows,
        "known_gap": "issue comments and workflow artifacts not represented by canonical receipts or the bounded historical design-point index remain outside the census",
        "skipped_invalid_json": skipped_invalid_json,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = census(args.evidence_dir)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
