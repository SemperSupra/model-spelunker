#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate(result: dict, expected_probe_ids: set[str] | None = None) -> None:
    if result.get("schema_version") != 1:
        raise RuntimeError("unsupported result schema")
    artifact = result.get("model_artifact") or {}
    if artifact.get("hydration_verified") is not True:
        raise RuntimeError("result is not bound to verified hydration")
    if artifact.get("identity_kind") not in {"content-manifest", "oci"}:
        raise RuntimeError("unsupported model identity kind")
    probes = result.get("probes") or []
    ids = [p.get("probe_case_id") for p in probes]
    if not ids or any(not value for value in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("probe result IDs must be non-empty and unique")
    if expected_probe_ids is not None and set(ids) != expected_probe_ids:
        raise RuntimeError(f"probe set mismatch: expected={sorted(expected_probe_ids)}, actual={sorted(ids)}")
    for probe in probes:
        if probe.get("status") != "passed":
            raise RuntimeError(f"probe did not pass: {probe.get('probe_case_id')}")
        if not isinstance((probe.get("behavior") or {}).get("generated_text"), str):
            raise RuntimeError(f"missing behavior output: {probe.get('probe_case_id')}")
        top = (probe.get("probability_surface") or {}).get("top_tokens") or []
        if not top:
            raise RuntimeError(f"missing probability surface: {probe.get('probe_case_id')}")
        layers = (probe.get("activation_cartography") or {}).get("last_input_token") or []
        if len(layers) < 2:
            raise RuntimeError(f"missing activation summaries: {probe.get('probe_case_id')}")
        if float((probe.get("timing") or {}).get("execution_seconds", -1)) < 0:
            raise RuntimeError(f"invalid timing: {probe.get('probe_case_id')}")
    economics = result.get("batch_economics") or {}
    if economics.get("probe_count") != len(probes):
        raise RuntimeError("batch economics probe_count mismatch")
    if float(economics.get("mean_marginal_probe_seconds", -1)) < 0:
        raise RuntimeError("invalid mean marginal probe timing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--probes", type=Path, default=Path("experiments/mvp/probes.json"))
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    probe_set = json.loads(args.probes.read_text(encoding="utf-8"))
    expected = {case["probe_case_id"] for case in probe_set["cases"]}
    validate(result, expected)
    print(json.dumps({"terminal_state": "PASS_RESULT_CONSISTENCY", "probe_count": len(expected)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
