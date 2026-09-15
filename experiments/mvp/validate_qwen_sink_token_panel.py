#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

EXPECTED_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
EXPECTED_REVISION = "ec7ddfa904d4d447eedd0b7f126df16957734abb"
EXPECTED_CAL = 4
EXPECTED_HOLD = 8


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
    jsonschema.validate(b, json.loads(args.schema.read_text()))
    finite_tree(b)

    assert b["probe_id"] == "qwen-sink-token-identity-panel-v1"
    assert b["access_tier"] == "A2"
    assert b["evidence_level"] == "PREDICTIVE"
    assert b["model_identity"]["repository"] == EXPECTED_MODEL
    assert b["model_identity"]["revision"] == EXPECTED_REVISION
    prov = b["artifact_provenance"]
    assert prov["tracked"] is True and prov["verified"] is True
    assert prov["upstream_repository"] == EXPECTED_MODEL
    assert prov["upstream_revision"] == EXPECTED_REVISION
    assert prov["identity_kind"] == "content-manifest"
    assert prov["identity_digest"].startswith("sha256:")

    obs = b["observations"]
    assert len(obs["calibration_tasks"]) == EXPECTED_CAL
    assert len(obs["holdout_tasks"]) == EXPECTED_HOLD
    assert len(obs["eligible_panel"]) >= 6
    assert len({x["task_id"] for x in obs["holdout_tasks"]}) == EXPECTED_HOLD
    for split in ("calibration_tasks", "holdout_tasks"):
        for task in obs[split]:
            for row in task["conditions"].values():
                assert 1 <= int(row["candidate_surface"]["correct_rank"]) <= 5
                if row["kind"] != "baseline":
                    mass = float(row["attention_sink_prefix_mass"])
                    assert 0.0 <= mass <= 1.000001

    d = b["derived_metrics"]
    assert d["attention_sanity_head"] == {"layer": 11, "head": 13}
    one_token = [x for x in d["panel_summary"].values() if x["kind"] == "one-token"]
    assert len(one_token) >= 6
    assert len(d["frozen_calibration_top3"]) == 3
    assert set(d["calibration_rank"]) == set(d["holdout_rank"])

    print(json.dumps({
        "validated": True,
        "run_id": b["provenance"]["run_id"],
        "model": EXPECTED_MODEL,
        "revision": EXPECTED_REVISION,
        "calibration_tasks": EXPECTED_CAL,
        "holdout_tasks": EXPECTED_HOLD,
        "eligible_tokens": len(one_token),
        "rank_correlation": d["calibration_holdout_rank_correlation"],
        "margin_correlation": d["calibration_holdout_margin_correlation"],
        "manifest": prov["identity_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
