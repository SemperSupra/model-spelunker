#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import jsonschema
ROOT=Path(__file__).resolve().parents[2]; SCHEMA=ROOT/"schemas"/"observation-bundle.schema.json"
LOGICAL_ID="forecast/chronos/bolt-tiny"; REV="a0e552de83495b5c28c14c71c374f3e33280b340"; AMPS=[0.5,1.0,2.0,5.0,10.0]; LAGS=[0,1,2,4,8,15,16,17,31,32,33,63]
def finite(v): return isinstance(v,(int,float)) and math.isfinite(float(v))
def hjson(v): return "sha256:"+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 p=argparse.ArgumentParser(); p.add_argument("bundle",type=Path); p.add_argument("candidate",type=Path); a=p.parse_args(); b=json.loads(a.bundle.read_text()); c=json.loads(a.candidate.read_text()); jsonschema.validate(b,json.loads(SCHEMA.read_text()))
 assert b["probe_id"]=="chronos-bolt-impulse-response-map-v1" and b["instrument_version"]=="mvp-2" and b["access_tier"]=="A1" and b["evidence_level"]=="REPRODUCED"
 ap=b["artifact_provenance"]; assert ap["tracked"] and ap["verified"] and ap["logical_artifact_id"]==LOGICAL_ID and ap["upstream_revision"]==REV and ap["identity_digest"]==c["oci"]["digest"]
 o=b["observations"]; pr=o["protocol"]; assert pr["context_length"]==128 and pr["prediction_length"]==32 and pr["patch_size"]==16 and pr["patch_stride"]==16 and pr["full_forecast_tensors_persisted"] is False and pr["repeatability_controls_batch_composition"] is True
 assert [float(r["amplitude"]) for r in o["positive_amplitude_sweep"]]==AMPS
 assert [int(r["lag_from_end"]) for r in o["position_sweep"]]==LAGS
 for r in o["positive_amplitude_sweep"]:
  assert r["forecast"]["finite"] is True
  for k in ("rescaled_to_amp5_max_abs_delta","rescaled_to_amp5_mean_abs_delta","rescaled_to_amp5_cosine_distance"): assert finite(r[k]) and r[k]>=-1e-6
 s=o["sign_reversal"]
 for k in ("negative_vs_negated_reversed_positive_max_abs_delta","negative_vs_negated_reversed_positive_mean_abs_delta","negative_vs_negated_reversed_positive_cosine_distance"): assert finite(s[k]) and s[k]>=-1e-6
 for r in o["position_sweep"]:
  assert 0<=r["offset_within_patch"]<16 and r["patch_index"]>=0 and r["forecast"]["finite"] is True
  for k in ("median_mean_abs_delta_from_lag0","median_max_abs_delta_from_lag0","full_forecast_cosine_distance_from_lag0"): assert finite(r[k]) and r[k]>=-1e-6
 rep=o["repeatability"]
 assert set(rep)=={"same_batch_amplitude_repeat","amp5_reference_vs_position_batch_lag0","amp5_reference_vs_singleton","position_batch_lag0_vs_singleton"}
 for row in rep.values():
  assert isinstance(row["hash_equal"],bool)
  for k in ("max_abs_delta","mean_abs_delta","cosine_distance"): assert finite(row[k]) and row[k]>=-1e-6
 assert rep["same_batch_amplitude_repeat"]["hash_equal"] is True and rep["same_batch_amplitude_repeat"]["max_abs_delta"]<=1e-6
 d=b["derived_metrics"]; assert d["same_batch_repeat_exact"] is True and d["reference_repeat_exact"] is True and all(v is True for v in d["portable_method_checks"].values())
 for k in ("positive_amplitude_rescaled_max_delta","positive_amplitude_rescaled_mean_delta","negative_sign_symmetry_max_delta","nonterminal_within_final_patch_median_delta_mean","cross_patch_median_delta_mean","cross_batch_position_max_abs_delta","cross_batch_singleton_max_abs_delta"): assert finite(d[k]) and d[k]>=-1e-6
 assert int(d["largest_position_effect"]) in LAGS
 assert abs(d["cross_batch_position_max_abs_delta"]-rep["amp5_reference_vs_position_batch_lag0"]["max_abs_delta"])<=1e-12
 assert abs(d["cross_batch_singleton_max_abs_delta"]-rep["amp5_reference_vs_singleton"]["max_abs_delta"])<=1e-12
 assert b["provenance"]["raw_output_hash"]==hjson({"observations":o,"derived_metrics":d})
 print(json.dumps({"valid":True,"probe_id":b["probe_id"],"identity_digest":ap["identity_digest"],"amplitude_rescaled_max":d["positive_amplitude_rescaled_max_delta"],"negative_symmetry_max":d["negative_sign_symmetry_max_delta"],"nonterminal_within_patch_mean":d["nonterminal_within_final_patch_median_delta_mean"],"cross_patch_mean":d["cross_patch_median_delta_mean"],"largest_position_effect":d["largest_position_effect"],"same_batch_repeat_exact":d["same_batch_repeat_exact"],"cross_batch_position_max":d["cross_batch_position_max_abs_delta"],"cross_batch_singleton_max":d["cross_batch_singleton_max_abs_delta"],"cross_batch_exactness_not_acceptance_gate":True,"scientific_outcome_not_acceptance_gate":True},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
