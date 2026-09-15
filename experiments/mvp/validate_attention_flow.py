#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

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

    assert bundle["access_tier"] == "A2"
    assert bundle["evidence_level"] == "RELATIONAL"
    provenance = bundle["artifact_provenance"]
    assert provenance["tracked"] is True
    assert provenance["verified"] is True
    assert provenance["identity_kind"] == "content-manifest"
    assert provenance["identity_digest"].startswith("sha256:")

    tasks = bundle["observations"]["heldout_tasks"]
    assert len(tasks) == EXPECTED_TASKS
    layer_count = None
    head_count = None
    for task in tasks:
        counts = task["region_token_counts"]
        assert counts["user-content"] > 0
        assert counts["answer-boundary"] > 0
        assert counts["all-aligned"] == counts["user-content"] + counts["answer-boundary"]
        assert counts["start_prompt_tokens"] > counts["no_prompt_tokens"]
        assert len(task["baseline_no_start"]["candidate_scores"]) == 5
        assert len(task["actual_start_target"]["candidate_scores"]) == 5
        layers = task["layers"]
        if layer_count is None:
            layer_count = len(layers)
        assert len(layers) == layer_count and layer_count > 0
        for layer in layers:
            assert 0.0 <= float(layer["user_hidden_cosine_distance"]) <= 2.000001
            assert 0.0 <= float(layer["boundary_hidden_cosine_distance"]) <= 2.000001
            heads = layer["heads"]
            if head_count is None:
                head_count = len(heads)
            assert len(heads) == head_count and head_count > 0
            for head in heads:
                for field in ("no_user_mass", "start_user_mass", "no_boundary_mass", "start_boundary_mass"):
                    assert 0.0 <= float(head[field]) <= 1.000001
                assert 0.0 <= float(head["aligned_normalized_tv"]) <= 1.000001
                assert float(head["aligned_raw_l1"]) >= 0.0

    derived = bundle["derived_metrics"]
    assert len(derived["head_summary"]) == layer_count * head_count
    assert len(derived["regional_hidden_summary"]) == layer_count
    assert 1 <= len(derived["top_user_attention_change_heads"]) <= 12
    assert 1 <= len(derived["top_aligned_attention_tv_heads"]) <= 12
    assert 1 <= len(derived["top_user_hidden_divergence_layers"]) <= 8
    assert bundle["provenance"]["environment"]["attention_implementation"] == "eager"

    print(json.dumps({
        "validated": True,
        "run_id": bundle["provenance"]["run_id"],
        "artifact_identity": provenance["identity_digest"],
        "heldout_tasks": len(tasks),
        "layers": layer_count,
        "heads_per_layer": head_count,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
