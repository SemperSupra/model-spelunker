#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

CAL_TASKS = 4
HOLD_TASKS = 6
MIN_ELIGIBLE = 6


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
    assert bundle["evidence_level"] == "PREDICTIVE"
    provenance = bundle["artifact_provenance"]
    assert provenance["tracked"] is True and provenance["verified"] is True
    assert provenance["identity_digest"].startswith("sha256:")

    obs = bundle["observations"]
    eligible = obs["eligible_panel"]
    assert len(eligible) >= MIN_ELIGIBLE
    eligible_ids = {x["panel_id"] for x in eligible}
    assert len(eligible_ids) == len(eligible)
    assert all(len(x["token_ids"]) == 1 for x in eligible)
    assert all(int(x["token_id"]) == int(x["token_ids"][0]) for x in eligible)
    assert all(len(x["token_ids"]) != 1 for x in obs["ineligible_preregistered_panel"])

    conditions = eligible_ids | {"baseline-none", "baseline-newline"}
    cal = obs["calibration_tasks"]
    hold = obs["holdout_tasks"]
    assert len(cal) == CAL_TASKS
    assert len(hold) == HOLD_TASKS
    for task in cal + hold:
        assert set(task["conditions"]) == conditions
        for pid, row in task["conditions"].items():
            surface = row["candidate_surface"]
            assert len(surface["candidate_scores"]) == 5
            assert 1 <= int(surface["correct_rank"]) <= 5
            sink = float(row["l18h8_prefix_attention_mass"])
            assert 0.0 <= sink <= 1.000001
            if pid == "baseline-none":
                assert sink <= 1e-5

    derived = bundle["derived_metrics"]
    panel_summary = derived["panel_summary"]
    assert set(panel_summary) == conditions
    for pid, row in panel_summary.items():
        assert 0.0 <= float(row["calibration_top1_rate"]) <= 1.0
        assert 0.0 <= float(row["holdout_top1_rate"]) <= 1.0
        if pid != "baseline-none":
            # The prior reps predict a saturated attention sink. Keep the threshold
            # deliberately loose enough to detect a falsifier rather than hard-code ~1.
            assert 0.5 <= float(row["mean_sink_mass"]) <= 1.000001

    cal_rank = derived["calibration_rank"]
    hold_rank = derived["holdout_rank"]
    transfer = derived["transfer"]
    assert set(cal_rank) == eligible_ids
    assert set(hold_rank) == eligible_ids
    assert set(transfer) == eligible_ids
    assert sorted(int(x) for x in cal_rank.values()) == list(range(1, len(eligible) + 1))
    assert sorted(int(x) for x in hold_rank.values()) == list(range(1, len(eligible) + 1))
    frozen = derived["frozen_calibration_top3"]
    assert len(frozen) == min(3, len(eligible))
    assert len(set(frozen)) == len(frozen)
    assert set(frozen).issubset(eligible_ids)
    assert all(bool(transfer[x]["frozen_top3"]) == (x in frozen) for x in eligible_ids)
    assert derived["attention_sanity_head"] == {"layer": 18, "head": 8}

    print(json.dumps({
        "validated": True,
        "run_id": bundle["provenance"]["run_id"],
        "artifact_identity": provenance["identity_digest"],
        "eligible_tokens": len(eligible),
        "calibration_tasks": len(cal),
        "holdout_tasks": len(hold),
        "frozen_top3": frozen,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
