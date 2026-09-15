#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

EXPECTED_TASKS = 16
EXPECTED_CONDITIONS = {"baseline-newline", "frozen-A", "letter-B", "neutral-x", "role-user"}


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

    assert b["probe_id"] == "sink-token-frozen-A-replication-v1"
    assert b["access_tier"] == "A2"
    assert b["evidence_level"] == "PREDICTIVE"
    prov = b["artifact_provenance"]
    assert prov["tracked"] is True and prov["verified"] is True
    assert prov["identity_digest"].startswith("sha256:")

    conditions = b["observations"]["conditions"]
    assert {c["condition_id"] for c in conditions} == EXPECTED_CONDITIONS
    cmap = {c["condition_id"]: c for c in conditions}
    assert cmap["frozen-A"]["token_id"] == 49
    assert cmap["neutral-x"]["token_id"] == 104
    assert cmap["role-user"]["token_id"] == 4093
    assert isinstance(cmap["letter-B"]["token_id"], int)

    tasks = b["observations"]["holdout_tasks"]
    assert len(tasks) == EXPECTED_TASKS
    assert len({t["task_id"] for t in tasks}) == EXPECTED_TASKS
    for task in tasks:
        rows = task["conditions"]
        assert set(rows) == EXPECTED_CONDITIONS
        for cid, row in rows.items():
            assert 1 <= int(row["correct_rank"]) <= 5
            assert isinstance(row["correct_top1"], bool)
            assert 0.0 <= float(row["l18h8_prefix_attention_mass"]) <= 1.000001

    summary = b["derived_metrics"]["condition_summary"]
    assert set(summary) == EXPECTED_CONDITIONS
    for row in summary.values():
        assert int(row["n"]) == EXPECTED_TASKS
        assert 0.0 <= float(row["top1_rate"]) <= 1.0
        assert 1.0 <= float(row["mean_correct_rank"]) <= 5.0

    primary = b["derived_metrics"]["primary_A_vs_newline"]
    assert primary["frozen_candidate"] == "frozen-A"
    assert primary["baseline"] == "baseline-newline"
    assert int(primary["positive_margin_delta_tasks"]) + int(primary["negative_margin_delta_tasks"]) <= EXPECTED_TASKS
    assert len(b["derived_metrics"]["task_margin_deltas_A_vs_newline"]) == EXPECTED_TASKS

    print(json.dumps({
        "validated": True,
        "run_id": b["provenance"]["run_id"],
        "tasks": EXPECTED_TASKS,
        "A_token_id": 49,
        "mean_margin_delta": primary["mean_margin_delta"],
        "top1_rate_delta": primary["top1_rate_delta"],
        "mean_rank_delta": primary["mean_rank_delta"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
