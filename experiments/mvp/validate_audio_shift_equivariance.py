#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import jsonschema

ROOT=Path(__file__).resolve().parents[2]
SCHEMA=ROOT/"schemas"/"observation-bundle.schema.json"
DIGEST="sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
FIXTURE_SHA="sha256:63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715"
SILENCES=[0.25,0.5,1.0,2.0]

def finite(v): return isinstance(v,(int,float)) and math.isfinite(float(v))
def hjson(v): return "sha256:"+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def chk_search(s,radius):
    assert s["radius"]==radius and len(s["tested"])>=radius+1
    offs=[x["offset_frames"] for x in s["tested"]]
    assert s["expected_offset_frames"] in offs
    assert s["best"]["offset_frames"] in offs
    for x in s["tested"]:
        assert int(x["common_frames"])>0
        for k in ("mean_cosine_distance","median_cosine_distance","relative_frobenius_difference"):
            assert finite(x[k]) and x[k]>=-1e-6

def main():
    p=argparse.ArgumentParser(); p.add_argument("bundle",type=Path); a=p.parse_args(); b=json.loads(a.bundle.read_text())
    jsonschema.validate(b,json.loads(SCHEMA.read_text()))
    assert b["probe_id"]=="audio-shift-equivariance-faster-whisper-tiny-v1"
    assert b["instrument"]=="audio-known-shift-offset-search-suite"
    assert b["access_tier"]=="A2" and b["evidence_level"]=="RELATIONAL"
    ap=b["artifact_provenance"]; assert ap["tracked"] and ap["identity_digest"]==DIGEST and ap["verified"]
    o=b["observations"]; assert o["fixture"]["sha256"]==FIXTURE_SHA
    proto=o["protocol"]; assert proto["feature_offset_search_radius"]==2 and proto["encoder_offset_search_radius"]==6 and proto["interior_trim_encoder_frames_each_edge"]==32
    props=proto["reference_architecture"]["observed_properties"]; assert "audio encoder conv2 stride=2" in props and "fixed sinusoidal positional embedding added after convolution" in props
    rows=o["silence_shift_rows"]; assert [float(r["silence_seconds"]) for r in rows]==SILENCES
    for r in rows:
        assert r["feature_expected_offset_frames"]>0 and r["encoder_expected_offset_frames"]>0
        chk_search(r["feature_search"],2); chk_search(r["encoder_search_full"],6); chk_search(r["encoder_search_interior_trim32"],6)
        bins=r["best_offset_position_bins"]; assert set(bins)=={"early","middle","late"}; assert all(finite(v) and v>=-1e-6 for v in bins.values())
    d=b["derived_metrics"]; assert d["baseline_repeat_encoder_hash_equal"] is True
    assert len(d["feature_best_mean_cosine_distances"])==4 and len(d["encoder_best_offset_deltas"])==4 and len(d["encoder_best_mean_cosine_distances"])==4 and len(d["encoder_interior_best_mean_cosine_distances"])==4
    assert all(finite(v) for k in ("feature_best_mean_cosine_distances","encoder_best_mean_cosine_distances","encoder_expected_mean_cosine_distances","encoder_interior_best_mean_cosine_distances") for v in d[k])
    assert b["provenance"]["raw_output_hash"]==hjson({"observations":o,"derived_metrics":d})
    print(json.dumps({"valid":True,"probe_id":b["probe_id"],"feature_exact":d["all_feature_best_offsets_equal_expected"],"encoder_offset_deltas":d["encoder_best_offset_deltas"],"encoder_best":d["encoder_best_mean_cosine_distances"],"scientific_outcome_not_acceptance_gate":True},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
