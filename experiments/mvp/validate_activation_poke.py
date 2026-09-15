#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

EXPECTED_LAYERS = {5, 8}
EXPECTED_TASKS = 4
EXPECTED_VARIANTS_PER_LAYER = 5


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

    assert bundle["access_tier"] == "A4"
    assert bundle["evidence_level"] == "CAUSAL"
    provenance = bundle["artifact_provenance"]
    assert provenance["tracked"] is True
    assert provenance["verified"] is True
    assert provenance["identity_kind"] == "content-manifest"
    assert provenance["identity_digest"].startswith("sha256:")

    calibration = bundle["observations"]["calibration"]
    assert {int(x["layer"]) for x in calibration} == EXPECTED_LAYERS
    for item in calibration:
        assert item["calibration_prompt_count"] == 4
        assert item["direction_l2"] > 0
        assert abs(item["direction_l2"] - item["random_control_l2"]) <= max(1e-6, item["direction_l2"] * 1e-5)
        assert len(item["per_prompt"]) == 4

    tasks = bundle["observations"]["heldout_tasks"]
    assert len(tasks) == EXPECTED_TASKS
    for task in tasks:
        assert len(task["candidates"]) == 5
        assert task["correct"] in task["candidates"]
        assert task["baseline_surface_distance_to_start"] >= 0
        assert task["baseline_final_hidden_cosine_distance_to_start"] >= 0
        for key in ("baseline_no_start", "actual_start_target"):
            surface = task[key]
            assert len(surface["candidate_scores"]) == 5
            assert surface["candidate_winner"] in task["candidates"]
            assert 1 <= int(surface["correct_rank"]) <= 5
        interventions = task["interventions"]
        assert len(interventions) == len(EXPECTED_LAYERS) * EXPECTED_VARIANTS_PER_LAYER
        per_layer = {layer: [] for layer in EXPECTED_LAYERS}
        for intervention in interventions:
            layer = int(intervention["layer"])
            assert layer in EXPECTED_LAYERS
            per_layer[layer].append(intervention)
            assert intervention["control_type"] in {"direction", "random"}
            assert len(intervention["surface"]["candidate_scores"]) == 5
            assert 1 <= int(intervention["surface"]["correct_rank"]) <= 5
        for layer, rows in per_layer.items():
            assert len(rows) == EXPECTED_VARIANTS_PER_LAYER, (task["task_id"], layer, len(rows))
            random_rows = [x for x in rows if x["control_type"] == "random"]
            direction_rows = [x for x in rows if x["control_type"] == "direction"]
            assert len(random_rows) == 1
            assert len(direction_rows) == 4
            assert {float(x["alpha"]) for x in direction_rows} == {-1.0, 0.5, 1.0, 2.0}

    aggregates = bundle["derived_metrics"]["aggregate_variants"]
    assert len(aggregates) == len(EXPECTED_LAYERS) * EXPECTED_VARIANTS_PER_LAYER
    for row in aggregates.values():
        assert int(row["n"]) == EXPECTED_TASKS
        assert 0.0 <= float(row["top1_correct_rate"]) <= 1.0

    print(json.dumps({
        "validated": True,
        "run_id": bundle["provenance"]["run_id"],
        "artifact_identity": provenance["identity_digest"],
        "layers": sorted(EXPECTED_LAYERS),
        "heldout_tasks": len(tasks),
        "aggregate_variants": len(aggregates),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
