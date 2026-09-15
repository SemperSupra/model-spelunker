#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

LAYERS = {5, 8}
WIDTHS = {"1", "4", "all"}
CONTROL_TYPES = {"direct", "self", "random"}
TASKS = 4
VARIANTS_PER_TASK = len(LAYERS) * len(WIDTHS) * len(CONTROL_TYPES)


def finite_tree(value, path="root"):
    if isinstance(value, dict):
        for key, child in value.items():
            finite_tree(child, f"{path}.{key}")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            finite_tree(child, f"{path}[{i}]")
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
    assert provenance["tracked"] is True and provenance["verified"] is True
    assert provenance["identity_kind"] == "content-manifest"
    assert provenance["identity_digest"].startswith("sha256:")

    tasks = bundle["observations"]["heldout_tasks"]
    assert len(tasks) == TASKS
    for task in tasks:
        assert len(task["candidates"]) == 5
        assert task["correct"] in task["candidates"]
        rows = task["interventions"]
        assert len(rows) == VARIANTS_PER_TASK, (task["task_id"], len(rows))
        seen = set()
        for row in rows:
            layer = int(row["layer"])
            width = str(row["width_spec"])
            control = row["control_type"]
            assert layer in LAYERS
            assert width in WIDTHS
            assert control in CONTROL_TYPES
            assert 1 <= int(row["width_tokens"]) <= int(task["baseline_no_start"]["input_tokens"])
            assert len(row["surface"]["candidate_scores"]) == 5
            assert 1 <= int(row["surface"]["correct_rank"]) <= 5
            seen.add((layer, width, control))
        assert len(seen) == VARIANTS_PER_TASK

    derived = bundle["derived_metrics"]
    aggregates = derived["aggregate_variants"]
    assert len(aggregates) == VARIANTS_PER_TASK
    for row in aggregates.values():
        assert int(row["n"]) == TASKS
        assert 0.0 <= float(row["top1_correct_rate"]) <= 1.0

    # Self-patching must behave as a null intervention; otherwise the hook itself is suspect.
    assert float(derived["self_patch_max_surface_logprob_delta"]) <= 1e-5
    assert abs(float(derived["self_patch_max_final_hidden_cosine_distance"])) <= 1e-5

    print(json.dumps({
        "validated": True,
        "run_id": bundle["provenance"]["run_id"],
        "artifact_identity": provenance["identity_digest"],
        "heldout_tasks": len(tasks),
        "variants_per_task": VARIANTS_PER_TASK,
        "aggregate_variants": len(aggregates),
        "self_patch_max_surface_logprob_delta": derived["self_patch_max_surface_logprob_delta"],
        "self_patch_max_final_hidden_cosine_distance": derived["self_patch_max_final_hidden_cosine_distance"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
