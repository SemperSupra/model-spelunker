#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, importlib.metadata, json, math, os, platform, resource, sys, time
from pathlib import Path
from typing import Any
import numpy as np
import torch
from chronos import BaseChronosPipeline, ChronosBoltPipeline

LOGICAL_ID="forecast/chronos/bolt-tiny"
UPSTREAM_REPO="amazon/chronos-bolt-tiny"
REV="a0e552de83495b5c28c14c71c374f3e33280b340"
QUANTILES=[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9]
AMPLITUDES=[0.5,1.0,2.0,5.0,10.0]
LAGS=[0,1,2,4,8,15,16,17,31,32,33,63]
CONTEXT_LENGTH=128
HORIZON=32


def hbytes(b:bytes)->str:return "sha256:"+hashlib.sha256(b).hexdigest()
def hjson(v:Any)->str:return hbytes(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode())
def th(x:torch.Tensor)->str:return hbytes(x.detach().cpu().to(torch.float32).contiguous().numpy().tobytes())

def cosine(a:torch.Tensor,b:torch.Tensor)->float:
    x=a.detach().cpu().to(torch.float64).reshape(-1); y=b.detach().cpu().to(torch.float64).reshape(-1)
    den=float(torch.linalg.vector_norm(x)*torch.linalg.vector_norm(y))
    return 0.0 if den<=1e-12 and torch.allclose(x,y) else (1.0 if den<=1e-12 else float(1.0-torch.dot(x,y)/den))

def impulse(amplitude:float,lag:int)->torch.Tensor:
    if not 0<=lag<CONTEXT_LENGTH: raise ValueError(lag)
    x=torch.zeros(CONTEXT_LENGTH,dtype=torch.float32); x[-1-lag]=amplitude; return x

def summary(f:torch.Tensor)->dict[str,Any]:
    f=f.detach().cpu().to(torch.float32); med=f[4]; width=f[8]-f[0]; crossings=f[:-1]>f[1:]
    return {"sha256_float32":th(f),"median_first":float(med[0]),"median_last":float(med[-1]),"median_mean":float(med.mean()),"median_min":float(med.min()),"median_max":float(med.max()),"median_delta_last_minus_first":float(med[-1]-med[0]),"q10_q90_width_mean":float(width.mean()),"q10_q90_width_max":float(width.max()),"quantile_crossing_cells":int(crossings.sum()),"finite":bool(torch.isfinite(f).all())}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--model-dir",type=Path,required=True); p.add_argument("--candidate",type=Path,required=True); p.add_argument("--candidate-ref",required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    os.environ["HF_HUB_OFFLINE"]="1"; os.environ["TRANSFORMERS_OFFLINE"]="1"; started=time.perf_counter()
    c=json.loads(a.candidate.read_text()); assert c["logical_id"]==LOGICAL_ID and c["upstream"]["exact_revision"]==REV and c["oci"]["pullback_verified"]
    digest=c["oci"]["digest"]
    t=time.perf_counter(); pipe=BaseChronosPipeline.from_pretrained(str(a.model_dir),device_map="cpu",torch_dtype=torch.float32,local_files_only=True); load=time.perf_counter()-t
    if not isinstance(pipe,ChronosBoltPipeline): raise RuntimeError(type(pipe).__name__)
    patch_size=int(pipe.model.config.chronos_config["input_patch_size"]); patch_stride=int(pipe.model.config.chronos_config["input_patch_stride"])
    if patch_size!=16 or patch_stride!=16: raise RuntimeError(f"unexpected patch geometry {patch_size}/{patch_stride}")
    t=time.perf_counter()
    amp_contexts=[impulse(x,0) for x in AMPLITUDES]
    with torch.inference_mode(): amp=pipe.predict(amp_contexts,prediction_length=HORIZON,limit_prediction_length=True).float().cpu()
    ref_idx=AMPLITUDES.index(5.0); ref=amp[ref_idx]
    amp_rows=[]
    for i,A in enumerate(AMPLITUDES):
        restored=amp[i]*(5.0/A)
        amp_rows.append({"amplitude":A,"forecast":summary(amp[i]),"rescaled_to_amp5_max_abs_delta":float((restored-ref).abs().max()),"rescaled_to_amp5_mean_abs_delta":float((restored-ref).abs().mean()),"rescaled_to_amp5_cosine_distance":cosine(restored,ref)})

    with torch.inference_mode(): neg=pipe.predict([impulse(-5.0,0)],prediction_length=HORIZON,limit_prediction_length=True).float().cpu()[0]
    expected_neg=-torch.flip(ref,dims=[0])
    sign={"positive":summary(ref),"negative":summary(neg),"negative_vs_negated_reversed_positive_max_abs_delta":float((neg-expected_neg).abs().max()),"negative_vs_negated_reversed_positive_mean_abs_delta":float((neg-expected_neg).abs().mean()),"negative_vs_negated_reversed_positive_cosine_distance":cosine(neg,expected_neg)}

    pos_contexts=[impulse(5.0,lag) for lag in LAGS]
    with torch.inference_mode(): pos=pipe.predict(pos_contexts,prediction_length=HORIZON,limit_prediction_length=True).float().cpu()
    lag0=pos[0]
    position_rows=[]
    for i,lag in enumerate(LAGS):
        absolute_index=CONTEXT_LENGTH-1-lag
        position_rows.append({"lag_from_end":lag,"absolute_index":absolute_index,"patch_index":absolute_index//patch_size,"offset_within_patch":absolute_index%patch_size,"forecast":summary(pos[i]),"median_mean_abs_delta_from_lag0":float((pos[i,4]-lag0[4]).abs().mean()),"median_max_abs_delta_from_lag0":float((pos[i,4]-lag0[4]).abs().max()),"full_forecast_cosine_distance_from_lag0":cosine(pos[i],lag0)})

    zero=torch.zeros(CONTEXT_LENGTH,dtype=torch.float32)
    with torch.inference_mode(): zero_f=pipe.predict([zero],prediction_length=HORIZON,limit_prediction_length=True).float().cpu()[0]; repeat=pipe.predict([impulse(5.0,0)],prediction_length=HORIZON,limit_prediction_length=True).float().cpu()[0]
    exp=time.perf_counter()-t
    observations={"protocol":{"context_length":CONTEXT_LENGTH,"prediction_length":HORIZON,"patch_size":patch_size,"patch_stride":patch_stride,"quantiles":QUANTILES,"full_forecast_tensors_persisted":False},"zero_context":summary(zero_f),"positive_amplitude_sweep":amp_rows,"sign_reversal":sign,"position_sweep":position_rows,"reference_repeat":{"hash_equal":th(repeat)==th(ref),"max_abs_delta":float((repeat-ref).abs().max())}}
    within=[r for r in position_rows if r["lag_from_end"]<=15]; cross=[r for r in position_rows if r["lag_from_end"]>=16]
    derived={"positive_amplitude_rescaled_max_delta":max(r["rescaled_to_amp5_max_abs_delta"] for r in amp_rows),"positive_amplitude_rescaled_mean_delta":float(np.mean([r["rescaled_to_amp5_mean_abs_delta"] for r in amp_rows])),"negative_sign_symmetry_max_delta":sign["negative_vs_negated_reversed_positive_max_abs_delta"],"within_final_patch_median_delta_mean":float(np.mean([r["median_mean_abs_delta_from_lag0"] for r in within])),"cross_patch_median_delta_mean":float(np.mean([r["median_mean_abs_delta_from_lag0"] for r in cross])),"largest_position_effect":max(position_rows,key=lambda r:r["median_mean_abs_delta_from_lag0"])["lag_from_end"],"reference_repeat_exact":th(repeat)==th(ref),"portable_method_checks":{"positive_amplitude_sweep_executed":True,"negative_sign_test_executed":True,"within_patch_positions_executed":True,"cross_patch_positions_executed":True,"zero_context_control_executed":True,"reference_repeat_observed":th(repeat)==th(ref)}}
    raw=hjson({"observations":observations,"derived_metrics":derived}); git=os.getenv("GITHUB_SHA")
    bundle={"probe_id":"chronos-bolt-impulse-response-map-v1","instrument":"timeseries-impulse-amplitude-sign-position-suite","instrument_version":"mvp-1","model_identity":{"repository":UPSTREAM_REPO,"revision":REV,"logical_id":LOGICAL_ID,"model_class":"time-series-probabilistic-forecaster"},"artifact_provenance":{"tracked":True,"foundry_repository":"SemperSupra/model-artifact-foundry","logical_artifact_id":LOGICAL_ID,"upstream_provider":"huggingface","upstream_repository":UPSTREAM_REPO,"upstream_revision":REV,"identity_kind":"oci","identity_digest":digest,"foundry_record_ref":a.candidate_ref,"consumer_selection_ref":f"model-spelunker@{git}" if git else None,"verified":True,"verification_ref":"pullback-verified candidate Foundry hydration with forced-offline local reuse","tokenizer_artifact":None},"access_tier":"A1","evidence_level":"REPRODUCED","claim_tags":["TIME_SERIES","IMPULSE_RESPONSE","PATCH_POSITION","SCALE_INVARIANCE","SIGN_SYMMETRY","BOUNDARY_SEARCH"],"observations":observations,"derived_metrics":derived,"uncertainty":{"scope":"single synthetic impulse family; not a general anomaly-response benchmark","negative_scaling":"negative-scale quantile comparison reverses quantile order before comparison","patch_interpretation":"position sweep localizes functional sensitivity relative to declared patch geometry but does not isolate an internal component"},"known_assumptions":["positive impulse amplitude scaling is equivalent to positive scaling of the entire zero-baseline context","negative sign symmetry should compare q with 1-q under exact distributional sign reversal","lag positions around multiples of 16 are informative because input patch size and stride are both 16"],"known_failure_modes":["a single impulse is out-of-distribution relative to many natural time-series processes","patch-boundary effects can interact with absolute recency and context normalization","functional sensitivity does not establish causal attribution to patching alone"],"cost":{"model_load_seconds":load,"experiment_seconds":exp,"total_script_seconds":time.perf_counter()-started,"peak_rss_mib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.0},"provenance":{"run_id":os.getenv("GITHUB_RUN_ID","local"),"code_revision":git,"model_revision":REV,"tokenizer_revision":None,"environment":{"python":sys.version.split()[0],"platform":platform.platform(),"numpy":np.__version__,"torch":torch.__version__,"chronos_forecasting":importlib.metadata.version("chronos-forecasting")},"randomness":{"deterministic_forecast":True},"raw_input_hash":hjson({"amplitudes":AMPLITUDES,"lags":LAGS,"context_length":CONTEXT_LENGTH,"horizon":HORIZON}),"raw_output_hash":raw}}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(bundle,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"output":str(a.output),"amplitude_rescaled_max":derived["positive_amplitude_rescaled_max_delta"],"negative_symmetry_max":derived["negative_sign_symmetry_max_delta"],"within_patch_mean":derived["within_final_patch_median_delta_mean"],"cross_patch_mean":derived["cross_patch_median_delta_mean"],"largest_position_effect":derived["largest_position_effect"],"repeat":derived["reference_repeat_exact"]},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
