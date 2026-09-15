#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

EXPECTED_TASKS = 4
EXPECTED_CONDITIONS = {"neither", "marker-only", "role-only", "both"}
EXPECTED_HEADS = {(14, 1), (17, 3), (18, 6), (18, 7), (18, 8)}


def finite_tree(value, path="root"):
    if isinstance(value, dict):
        for key, child in value.items():
            finite_tree(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            finite_tree(child, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise AssertionError(f"non-finite float at {path}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--schema", type=Path, default=Path("schemas/observation-bundle.schema.json"))
    args = parser.parse_args()

    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    jsonschema.validate(bundle, schema)
    finite_tree(bundle)

    assert bundle["access_tier"] == "A2"
    assert bundle["evidence_level"] == "CAUSAL"
    provenance = bundle["artifact_provenance"]
    assert provenance["tracked"] is True
    assert provenance["verified"] is True
    assert provenance["identity_digest"].startswith("sha256:")

    prefix = bundle["observations"]["prefix_tokenization"]
    assert set(prefix) == EXPECTED_CONDITIONS
    assert prefix["neither"]["control_prefix_token_ids"] == []
    assert len(prefix["marker-only"]["control_prefix_token_ids"]) > 0
    assert len(prefix["role-only"]["control_prefix_token_ids"]) > 0
    assert len(prefix["both"]["control_prefix_token_ids"]) > 0

    tasks = bundle["observations"]["heldout_tasks"]
    assert len(tasks) == EXPECTED_TASKS
    for task in tasks:
        assert set(task["conditions"]) == EXPECTED_CONDITIONS
        for name, condition in task["conditions"].items():
            assert condition["marker"] in (0, 1)
            assert condition["role"] in (0, 1)
            assert len(condition["candidate_surface"]["candidate_scores"]) == 5
            assert 1 <= int(condition["candidate_surface"]["correct_rank"]) <= 5
            assert set(condition["head_metrics"]) == {f"L{l}H{h}" for l, h in EXPECTED_HEADS}
            for metric in condition["head_metrics"].values():
                for field in ("user_mass", "boundary_mass", "control_prefix_mass", "bos_mass"):
                    assert 0.0 <= float(metric[field]) <= 1.000001

    summary = bundle["derived_metrics"]["head_factor_summary"]
    assert {(int(row["layer"]), int(row["head"])) for row in summary} == EXPECTED_HEADS
    for row in summary:
        assert int(row["n"]) == EXPECTED_TASKS
        for metric in ("user_mass", "boundary_mass", "control_prefix_mass", "bos_mass"):
            assert set(row[metric + "_means"]) == EXPECTED_CONDITIONS
            effects = row[metric + "_factor_effects"]
            assert set(effects) == {"marker_main_effect", "role_main_effect", "interaction"}

    behavior = bundle["derived_metrics"]["behavior_summary"]
    assert set(behavior) == EXPECTED_CONDITIONS
    for row in behavior.values():
        assert int(row["n"]) == EXPECTED_TASKS
        assert 0.0 <= float(row["top1_rate"]) <= 1.0
        assert 1.0 <= float(row["mean_correct_rank"]) <= 5.0

    print(json.dumps({
        "validated": True,
        "run_id": bundle["provenance"]["run_id"],
        "artifact_identity": provenance["identity_digest"],
        "tasks": len(tasks),
        "heads": len(summary),
        "conditions": sorted(EXPECTED_CONDITIONS),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
