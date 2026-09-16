#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, math
from pathlib import Path
import jsonschema

REPO_ROOT=Path(__file__).resolve().parents[2]
SCHEMA=REPO_ROOT/"schemas"/"observation-bundle.schema.json"
EXPECTED_DIGEST="sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
EXPECTED_LANGS={"en","zh","ja","ko","fr","de","es","ru","ar"}
EXPECTED_CONDITIONS={"baseline","gain_0.125","snr_20db","snr_10db","silence_500ms"}
SOURCE_REPO="wudale/whisper-asr-server"; SOURCE_COMMIT="f86a51a04e5c9e6b82dc9f22c01ada4cb8c40c5f"

def finite(v): return isinstance(v,(int,float)) and math.isfinite(float(v))
def sha256_json(v): return "sha256:"+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def main():
    p=argparse.ArgumentParser(); p.add_argument("bundle",type=Path); a=p.parse_args(); b=json.loads(a.bundle.read_text())
    jsonschema.validate(b,json.loads(SCHEMA.read_text()))
    assert b["probe_id"]=="audio-multilingual-generalization-faster-whisper-tiny-v1"
    assert b["instrument"]=="audio-multilingual-feature-encoder-decoder-portability-suite"
    assert b["access_tier"]=="A2" and b["evidence_level"]=="REPRODUCED"
    ap=b["artifact_provenance"]; assert ap["tracked"] is True and ap["identity_kind"]=="oci" and ap["identity_digest"]==EXPECTED_DIGEST and ap["verified"] is True
    obs=b["observations"]; src=obs["panel_source"]; assert src["repository"]==SOURCE_REPO and src["commit"]==SOURCE_COMMIT and src["repository_license"]=="MIT"
    proto=obs["protocol"]; assert set(proto["conditions"])==EXPECTED_CONDITIONS and proto["full_encoder_tensor_persisted"] is False and proto["language_mode"]=="auto-detect"
    langs=obs["languages"]; assert len(langs)==9 and {x["id"] for x in langs}==EXPECTED_LANGS
    for lang in langs:
        assert lang["expected_language"]==lang["id"]
        s=lang["source"]; assert s["git_blob_sha1"] and len(s["git_blob_sha1"])==40; assert s["sha256"].startswith("sha256:") and len(s["sha256"])==71; assert int(s["size_bytes"])>1000
        rows=lang["conditions"]; assert len(rows)==5 and {r["condition"] for r in rows}==EXPECTED_CONDITIONS
        for r in rows:
            assert r["audio"]["samples"]>0 and finite(r["audio"]["duration_seconds"]) and r["audio"]["duration_seconds"]>0
            rep=r["representation"]; shape=rep["encoder_shape"]; assert len(shape)==3 and shape[0]==1 and shape[1]>0 and shape[2]>0
            assert rep["encoder_hash"].startswith("sha256:") and len(rep["encoder_hash"])==71
            g=rep["geometry_from_baseline"]; assert finite(g["pooled_cosine_distance"]); assert finite(g["unaligned"]["mean_cosine_distance"]); assert finite(g["unaligned"]["relative_frobenius_difference"])
            if r["condition"]=="silence_500ms":
                assert g["shift_aware"] is not None and g["shift_aware"]["feature_offset_frames"]==50 and g["shift_aware"]["encoder_offset_frames"]>0
                assert finite(g["shift_aware"]["encoder"]["mean_cosine_distance"])
            d=r["decoder"]; assert isinstance(d["transcript"],str); assert isinstance(d["detected_language"],str) and d["detected_language"]
            assert finite(d["language_probability"]); cd=d["char_distance_from_baseline"]; assert cd["char_edit_distance"]>=0 and finite(cd["normalized_char_edit_distance"])
        base=next(r for r in rows if r["condition"]=="baseline")
        assert abs(base["representation"]["geometry_from_baseline"]["pooled_cosine_distance"])<=1e-6
        assert base["decoder"]["char_distance_from_baseline"]["char_edit_distance"]==0
        rpt=lang["baseline_repeat"]; assert rpt["encoder_hash_equal"] is True and rpt["transcript_equal"] is True and rpt["detected_language_equal"] is True
    d=b["derived_metrics"]; assert d["baseline_expected_language_total"]==9 and 0<=d["baseline_expected_language_matches"]<=9
    assert d["all_baseline_encoder_repeats_exact"] is True and d["all_baseline_transcript_repeats_exact"] is True
    assert set(d["per_language"])==EXPECTED_LANGS
    assert b["provenance"]["raw_output_hash"]==sha256_json({"observations":obs,"derived_metrics":d})
    print(json.dumps({"valid":True,"languages":9,"baseline_language_matches":d["baseline_expected_language_matches"],"all_repeats_exact":True,"scientific_outcome_not_acceptance_gate":True},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
