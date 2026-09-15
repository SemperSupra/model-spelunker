#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

EXPECTED_LAYERS = {5, 8}
EXPECTED_REGIONS = {"user-content", "answer-boundary", "all-aligned"}
EXPECTED_CONTROLS = {"direct", "self", "random"}
EXPECTED_TASKS = 4


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

    tasks = bundle["observations"]["heldout_tasks"]
    assert len(tasks) == EXPECTED_TASKS
    expected_per_task = len(EXPECTED_LAYERS) * len(EXPECTED_REGIONS) * len(EXPECTED_CONTROLS)
    for task in tasks:
        assert set(task["region_token_counts"]) == EXPECTED_REGIONS
        assert all(int(v) > 0 for v in task["region_token_counts"].values())
        assert task["region_token_counts"]["all-aligned"] == (
            task["region_token_counts"]["user-content"] + task["region_token_counts"]["answer-boundary"]
        )
        rows = task["interventions"]
        assert len(rows) == expected_per_task
        seen = set()
        for row in rows:
            key = (int(row["layer"]), row["region"], row["control_type"])
            seen.add(key)
            assert int(row["layer"]) in EXPECTED_LAYERS
            assert row["region"] in EXPECTED_REGIONS
            assert row["control_type"] in EXPECTED_CONTROLS
            assert int(row["aligned_token_count"]) == int(task["region_token_counts"][row["region"]])
            surface = row["surface"]
            assert len(surface["candidate_scores"]) == 5
            assert 1 <= int(surface["correct_rank"]) <= 5
        expected_seen = {
            (layer, region, control)
            for layer in EXPECTED_LAYERS
            for region in EXPECTED_REGIONS
            for control in EXPECTED_CONTROLS
        }
        assert seen == expected_seen

    aggregates = bundle["derived_metrics"]["aggregate_variants"]
    assert len(aggregates) == len(EXPECTED_LAYERS) * len(EXPECTED_REGIONS) * len(EXPECTED_CONTROLS)
    for row in aggregates.values():
        assert int(row["n"]) == EXPECTED_TASKS
        assert 0.0 <= float(row["top1_correct_rate"]) <= 1.0

    assert float(bundle["derived_metrics"]["self_patch_max_surface_logprob_delta"]) <= 1e-5
    assert float(bundle["derived_metrics"]["self_patch_max_final_hidden_cosine_distance"]) <= 1e-5

    print(json.dumps({
        "validated": True,
        "run_id": bundle["provenance"]["run_id"],
        "artifact_identity": provenance["identity_digest"],
        "layers": sorted(EXPECTED_LAYERS),
        "regions": sorted(EXPECTED_REGIONS),
        "heldout_tasks": len(tasks),
        "aggregate_variants": len(aggregates),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
