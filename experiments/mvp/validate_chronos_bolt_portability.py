#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "observation-bundle.schema.json"
LOGICAL_ID = "forecast/chronos/bolt-tiny"
REVISION = "a0e552de83495b5c28c14c71c374f3e33280b340"
FAMILIES = {"constant","linear","seasonal","step","impulse"}


def finite(v) -> bool:
    return isinstance(v, (int,float)) and math.isfinite(float(v))


def hjson(v) -> str:
    data = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    p.add_argument("candidate", type=Path)
    args = p.parse_args()
    b = json.loads(args.bundle.read_text(encoding="utf-8"))
    c = json.loads(args.candidate.read_text(encoding="utf-8"))
    jsonschema.validate(b, json.loads(SCHEMA.read_text(encoding="utf-8")))

    assert b["probe_id"] == "chronos-bolt-timeseries-portability-v1"
    assert b["instrument"] == "timeseries-quantile-forecast-protocol-contrast-suite"
    assert b["access_tier"] == "A1" and b["evidence_level"] == "REPRODUCED"
    assert b["model_identity"]["logical_id"] == LOGICAL_ID
    assert b["model_identity"]["revision"] == REVISION

    ap = b["artifact_provenance"]
    assert ap["tracked"] is True and ap["verified"] is True
    assert ap["logical_artifact_id"] == LOGICAL_ID
    assert ap["upstream_revision"] == REVISION
    assert ap["identity_kind"] == "oci"
    assert ap["identity_digest"] == c["oci"]["digest"]
    assert c["logical_id"] == LOGICAL_ID and c["upstream"]["exact_revision"] == REVISION
    assert c["oci"]["pullback_verified"] is True

    o = b["observations"]
    proto = o["protocol"]
    assert proto["pipeline_class"] == "ChronosBoltPipeline"
    assert proto["quantiles"] == [0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9]
    assert proto["model_context_length"] >= 128 and proto["model_prediction_length"] >= 32
    assert proto["full_forecast_tensors_persisted"] is False

    base = o["baseline_families"]
    assert set(base) == FAMILIES
    for row in base.values():
        assert row["shape"] == [9,32]
        assert row["finite"] is True
        assert row["sha256_float32"].startswith("sha256:") and len(row["sha256_float32"]) == 71
        assert 0 <= row["quantile_crossing_cells"] <= row["quantile_comparisons"]
        for k in ("median_mean","q10_q90_width_mean"):
            assert finite(row[k])
        if row["median_mae_known_future"] is not None:
            assert finite(row["median_mae_known_future"]) and row["median_mae_known_future"] >= 0

    assert o["baseline_repeat"]["hash_equal"] is True
    assert finite(o["baseline_repeat"]["max_abs_delta"]) and o["baseline_repeat"]["max_abs_delta"] <= 1e-6
    hc = o["horizon_consistency"]
    assert finite(hc["h8_vs_h32_prefix_max_abs_delta"]) and finite(hc["h16_vs_h32_prefix_max_abs_delta"])
    for k in ("h8_hash","h16_hash","h32_hash"):
        assert hc[k].startswith("sha256:") and len(hc[k]) == 71

    aff = o["positive_affine_equivariance"]
    assert aff["scale"] > 0
    for k in ("restored_max_abs_delta","restored_mean_abs_delta","restored_cosine_distance"):
        assert finite(aff[k]) and aff[k] >= -1e-6

    rows = o["context_length_sensitivity"]
    assert [r["context_length"] for r in rows] == [128,64,32]
    for r in rows:
        assert r["finite"] is True
        assert finite(r["median_mean_abs_delta_from_len128"])
        assert finite(r["median_max_abs_delta_from_len128"])
    miss = o["missingness"]
    assert miss["finite"] is True
    assert finite(miss["median_mean_abs_delta_from_complete"])
    assert finite(miss["median_max_abs_delta_from_complete"])

    d = b["derived_metrics"]
    assert d["baseline_repeat_exact"] is True
    assert d["all_baseline_forecasts_finite"] is True
    assert d["missingness_forecast_finite"] is True
    assert 0 <= d["total_quantile_crossings"] <= d["total_quantile_comparisons"]
    assert set(d["known_future_median_mae"]) == {"constant","linear","seasonal"}
    assert all(finite(v) and v >= 0 for v in d["known_future_median_mae"].values())
    assert all(v is True for v in d["portable_method_checks"].values())

    assert b["provenance"]["raw_output_hash"] == hjson({"observations": o, "derived_metrics": d})
    print(json.dumps({
        "valid": True,
        "probe_id": b["probe_id"],
        "identity_digest": ap["identity_digest"],
        "quantile_crossings": d["total_quantile_crossings"],
        "known_future_mae": d["known_future_median_mae"],
        "horizon_consistency": hc,
        "affine": aff,
        "scientific_outcome_not_acceptance_gate": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
