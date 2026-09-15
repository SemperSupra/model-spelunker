#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

EXPECTED_TASKS = 6
EXPECTED_CONDITIONS = {"native", "raw", "newline_raw"}
EXPECTED_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
EXPECTED_REVISION = "ec7ddfa904d4d447eedd0b7f126df16957734abb"


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
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    p.add_argument("--schema", type=Path, default=Path("schemas/observation-bundle.schema.json"))
    args = p.parse_args()

    b = json.loads(args.bundle.read_text())
    schema = json.loads(args.schema.read_text())
    jsonschema.validate(b, schema)
    finite_tree(b)

    assert b["probe_id"] == "cross-model-portability-qwen25-v1"
    assert b["access_tier"] == "A2"
    assert b["evidence_level"] == "REPRODUCED"
    assert b["model_identity"]["repository"] == EXPECTED_MODEL
    assert b["model_identity"]["revision"] == EXPECTED_REVISION

    prov = b["artifact_provenance"]
    assert prov["tracked"] is True and prov["verified"] is True
    assert prov["upstream_repository"] == EXPECTED_MODEL
    assert prov["upstream_revision"] == EXPECTED_REVISION
    assert prov["identity_kind"] == "content-manifest"
    assert prov["identity_digest"].startswith("sha256:")

    tasks = b["observations"]["tasks"]
    assert len(tasks) == EXPECTED_TASKS
    assert len({t["task_id"] for t in tasks}) == EXPECTED_TASKS
    for task in tasks:
        assert set(task["conditions"]) == EXPECTED_CONDITIONS
        layer_counts = set()
        for condition, row in task["conditions"].items():
            assert 1 <= int(row["correct_rank"]) <= 5
            assert isinstance(row["correct_top1"], bool)
            assert len(row["candidate_scores"]) == 5
            assert len(row["hidden_summary"]) > 4
            assert len(row["attention_heads"]) > 0
            layer_counts.add(len(row["hidden_summary"]))
        assert len(layer_counts) == 1

    contrasts = b["observations"]["protocol_contrasts"]
    assert len(contrasts) == EXPECTED_TASKS
    assert all(len(x["layers"]) > 4 for x in contrasts)

    d = b["derived_metrics"]
    assert set(d["condition_summary"]) == EXPECTED_CONDITIONS
    assert len(d["mean_raw_native_layer_contrast"]) > 4
    assert set(d["top_first_token_attention_heads"]) == EXPECTED_CONDITIONS
    for condition in EXPECTED_CONDITIONS:
        assert len(d["top_first_token_attention_heads"][condition]) > 0
    checks = d["portable_instrument_checks"]
    assert all(checks.values())

    print(json.dumps({
        "validated": True,
        "run_id": b["provenance"]["run_id"],
        "model": EXPECTED_MODEL,
        "revision": EXPECTED_REVISION,
        "tasks": EXPECTED_TASKS,
        "conditions": d["condition_summary"],
        "manifest": prov["identity_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
