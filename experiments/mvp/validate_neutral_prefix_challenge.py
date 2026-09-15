#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

EXPECTED_TASKS = 4
EXPECTED_CONDITIONS = {"none", "newline", "neutral-x", "neutral-foo", "role-user", "role-assistant", "special-marker"}
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
    assert provenance["tracked"] is True and provenance["verified"] is True
    assert provenance["identity_digest"].startswith("sha256:")

    obs = bundle["observations"]
    assert set(obs["prefix_tokenization"]) == EXPECTED_CONDITIONS
    assert obs["prefix_tokenization"]["none"]["prefix_token_ids"] == []
    meta = obs["tokenizer_metadata"]
    assert isinstance(meta["all_special_tokens"], list)
    assert isinstance(meta["all_special_ids"], list)

    tasks = obs["heldout_tasks"]
    assert len(tasks) == EXPECTED_TASKS
    expected_metric_keys = {f"L{l}H{h}" for l, h in EXPECTED_HEADS}
    for task in tasks:
        assert set(task["conditions"]) == EXPECTED_CONDITIONS
        for condition in task["conditions"].values():
            assert len(condition["candidate_surface"]["candidate_scores"]) == 5
            assert 1 <= int(condition["candidate_surface"]["correct_rank"]) <= 5
            assert set(condition["head_metrics"]) == expected_metric_keys
            for metric in condition["head_metrics"].values():
                for field in ("prefix_mass", "user_mass", "boundary_mass"):
                    assert 0.0 <= float(metric[field]) <= 1.000001

    condition_summary = bundle["derived_metrics"]["condition_summary"]
    assert set(condition_summary) == EXPECTED_CONDITIONS
    for row in condition_summary.values():
        assert int(row["n"]) == EXPECTED_TASKS
        assert 0.0 <= float(row["top1_rate"]) <= 1.0
        assert 1.0 <= float(row["mean_correct_rank"]) <= 5.0

    head_summary = bundle["derived_metrics"]["head_condition_summary"]
    assert {(int(row["layer"]), int(row["head"])) for row in head_summary} == EXPECTED_HEADS
    for row in head_summary:
        assert set(row["conditions"]) == EXPECTED_CONDITIONS
        for metric in row["conditions"].values():
            for field in ("mean_prefix_mass", "mean_user_mass", "mean_boundary_mass"):
                assert 0.0 <= float(metric[field]) <= 1.000001

    print(json.dumps({
        "validated": True,
        "run_id": bundle["provenance"]["run_id"],
        "artifact_identity": provenance["identity_digest"],
        "tasks": len(tasks),
        "conditions": len(EXPECTED_CONDITIONS),
        "heads": len(EXPECTED_HEADS),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
