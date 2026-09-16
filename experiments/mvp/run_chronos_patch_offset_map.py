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
CONTEXT_LENGTH=128
HORIZON=32
AMPLITUDE=5.0
FINAL_PATCH_LAGS=list(range(16))
PATCH_TERMINAL_LAGS=[0,16,32,48,64,80,96,112]
LAGS=sorted(set(FINAL_PATCH_LAGS+PATCH_TERMINAL_LAGS))


def hbytes(b:bytes)->str:return "sha256:"+hashlib.sha256(b).hexdigest()
def hjson(v:Any)->str:return hbytes(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode())
def th(x:torch.Tensor)->str:return hbytes(x.detach().cpu().to(torch.float32).contiguous().numpy().tobytes())

def cosine(a:torch.Tensor,b:torch.Tensor)->float:
    x=a.detach().cpu().to(torch.float64).reshape(-1); y=b.detach().cpu().to(torch.float64).reshape(-1)
    den=float(torch.linalg.vector_norm(x)*torch.linalg.vector_norm(y))
    return 0.0 if den<=1e-12 and torch.allclose(x,y) else (1.0 if den<=1e-12 else float(1.0-torch.dot(x,y)/den))

def impulse(lag:int)->torch.Tensor:
    x=torch.zeros(CONTEXT_LENGTH,dtype=torch.float32); x[-1-lag]=AMPLITUDE; return x

def forecast_summary(f:torch.Tensor)->dict[str,Any]:
    f=f.detach().cpu().to(torch.float32)
    med=f[4]; width=f[8]-f[0]; crossings=f[:-1]>f[1:]
    return {
        "sha256_float32":th(f),
        "median_first":float(med[0]),"median_last":float(med[-1]),"median_mean":float(med.mean()),
        "median_min":float(med.min()),"median_max":float(med.max()),
        "median_abs_mean":float(med.abs().mean()),
        "median_delta_last_minus_first":float(med[-1]-med[0]),
        "q10_q90_width_mean":float(width.mean()),"q10_q90_width_max":float(width.max()),
        "quantile_crossing_cells":int(crossings.sum()),
        "quantile_crossing_fraction":float(crossings.float().mean()),
        "finite":bool(torch.isfinite(f).all()),
    }

def compare(a:torch.Tensor,b:torch.Tensor)->dict[str,Any]:
    return {"hash_equal":th(a)==th(b),"max_abs_delta":float((a-b).abs().max()),"mean_abs_delta":float((a-b).abs().mean()),"cosine_distance":cosine(a,b)}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--model-dir",type=Path,required=True); p.add_argument("--candidate",type=Path,required=True); p.add_argument("--candidate-ref",required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    os.environ["HF_HUB_OFFLINE"]="1"; os.environ["TRANSFORMERS_OFFLINE"]="1"; started=time.perf_counter()
    c=json.loads(a.candidate.read_text()); assert c["logical_id"]==LOGICAL_ID and c["upstream"]["exact_revision"]==REV and c["oci"]["pullback_verified"]
    digest=c["oci"]["digest"]
    t=time.perf_counter(); pipe=BaseChronosPipeline.from_pretrained(str(a.model_dir),device_map="cpu",torch_dtype=torch.float32,local_files_only=True); load=time.perf_counter()-t
    if not isinstance(pipe,ChronosBoltPipeline): raise RuntimeError(type(pipe).__name__)
    patch_size=int(pipe.model.config.chronos_config["input_patch_size"]); patch_stride=int(pipe.model.config.chronos_config["input_patch_stride"])
    quantiles=list(pipe.quantiles)
    if patch_size!=16 or patch_stride!=16 or quantiles!=[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9]: raise RuntimeError((patch_size,patch_stride,quantiles))
    contexts=[impulse(lag) for lag in LAGS]
    t=time.perf_counter()
    with torch.inference_mode():
        pred=pipe.predict(contexts,prediction_length=HORIZON,limit_prediction_length=True).float().cpu()
        repeat=pipe.predict(contexts,prediction_length=HORIZON,limit_prediction_length=True).float().cpu()
        zero=pipe.predict([torch.zeros(CONTEXT_LENGTH,dtype=torch.float32)],prediction_length=HORIZON,limit_prediction_length=True).float().cpu()[0]
    exp=time.perf_counter()-t
    if list(pred.shape)!=[len(LAGS),9,HORIZON]: raise RuntimeError(pred.shape)
    ref=pred[LAGS.index(0)]
    rows=[]
    for i,lag in enumerate(LAGS):
        idx=CONTEXT_LENGTH-1-lag
        rows.append({
            "lag_from_end":lag,"absolute_index":idx,"patch_index":idx//patch_size,"offset_within_patch":idx%patch_size,
            "is_final_patch":idx//patch_size==(CONTEXT_LENGTH//patch_size-1),"is_patch_terminal":idx%patch_size==patch_size-1,
            "forecast":forecast_summary(pred[i]),
            "median_mean_abs_delta_from_terminal_reference":float((pred[i,4]-ref[4]).abs().mean()),
            "median_max_abs_delta_from_terminal_reference":float((pred[i,4]-ref[4]).abs().max()),
            "full_forecast_cosine_distance_from_terminal_reference":cosine(pred[i],ref),
            "repeat":compare(pred[i],repeat[i]),
        })
    final_rows=sorted([r for r in rows if r["is_final_patch"]],key=lambda r:r["offset_within_patch"])
    terminal_rows=sorted([r for r in rows if r["is_patch_terminal"]],key=lambda r:r["patch_index"])
    nonterminal=[r for r in final_rows if not r["is_patch_terminal"]]
    ref_abs=next(r["forecast"]["median_abs_mean"] for r in final_rows if r["is_patch_terminal"])
    max_nonterminal=max(r["forecast"]["median_abs_mean"] for r in nonterminal)
    repeat_max=max(r["repeat"]["max_abs_delta"] for r in rows)
    observations={
        "protocol":{"context_length":CONTEXT_LENGTH,"prediction_length":HORIZON,"patch_size":patch_size,"patch_stride":patch_stride,"quantiles":quantiles,"amplitude":AMPLITUDE,"lags":LAGS,"full_forecast_tensors_persisted":False},
        "zero_context":forecast_summary(zero),"position_rows":rows,
    }
    derived={
        "position_count":len(rows),
        "final_patch_offset_count":len(final_rows),
        "patch_terminal_count":len(terminal_rows),
        "same_batch_repeat_exact":all(r["repeat"]["hash_equal"] for r in rows),
        "same_batch_repeat_max_abs_delta":repeat_max,
        "terminal_reference_median_abs_mean":ref_abs,
        "max_nonterminal_final_patch_median_abs_mean":max_nonterminal,
        "terminal_to_max_nonterminal_magnitude_ratio":float(ref_abs/max(max_nonterminal,1e-12)),
        "final_patch_offset_curve":[{"offset":r["offset_within_patch"],"lag":r["lag_from_end"],"median_abs_mean":r["forecast"]["median_abs_mean"],"median_delta_from_terminal":r["median_mean_abs_delta_from_terminal_reference"],"crossing_cells":r["forecast"]["quantile_crossing_cells"]} for r in final_rows],
        "patch_terminal_curve":[{"patch_index":r["patch_index"],"lag":r["lag_from_end"],"median_abs_mean":r["forecast"]["median_abs_mean"],"median_delta_from_terminal":r["median_mean_abs_delta_from_terminal_reference"],"crossing_cells":r["forecast"]["quantile_crossing_cells"]} for r in terminal_rows],
        "all_outputs_finite":all(r["forecast"]["finite"] for r in rows) and observations["zero_context"]["finite"],
        "quantile_crossing_positions":[r["lag_from_end"] for r in rows if r["forecast"]["quantile_crossing_cells"]>0],
    }
    raw=hjson({"observations":observations,"derived_metrics":derived}); git=os.getenv("GITHUB_SHA")
    bundle={"probe_id":"chronos-bolt-patch-offset-map-v1","instrument":"timeseries-patch-offset-terminal-position-map","instrument_version":"mvp-1","model_identity":{"repository":UPSTREAM_REPO,"revision":REV,"logical_id":LOGICAL_ID,"model_class":"time-series-probabilistic-forecaster"},"artifact_provenance":{"tracked":True,"foundry_repository":"SemperSupra/model-artifact-foundry","logical_artifact_id":LOGICAL_ID,"upstream_provider":"huggingface","upstream_repository":UPSTREAM_REPO,"upstream_revision":REV,"identity_kind":"oci","identity_digest":digest,"foundry_record_ref":a.candidate_ref,"consumer_selection_ref":f"model-spelunker@{git}" if git else None,"verified":True,"verification_ref":"pullback-verified candidate Foundry hydration with forced-offline local reuse","tokenizer_artifact":None},"access_tier":"A1","evidence_level":"REPRODUCED","claim_tags":["TIME_SERIES","PATCH_POSITION","BOUNDARY_SEARCH","QUANTILE_SURFACE","PROTOCOL_DEPENDENCE"],"observations":observations,"derived_metrics":derived,"uncertainty":{"scope":"single positive impulse amplitude on zero baseline; functional localization only","quantile_crossings":"reported directly from ordered model quantile outputs; no monotonic post-processing applied","causality":"patch-offset association does not identify an internal causal component"},"known_assumptions":["official Chronos-Bolt predict output is batch x ordered training quantiles x horizon","patch size and stride 16 make offsets 0..15 and terminal positions directly interpretable","fixed positive amplitude isolates position from the already-established positive scale equivariance"],"known_failure_modes":["zero-baseline impulses are synthetic and may be out-of-distribution","absolute recency and patch index remain coupled for the earlier-patch terminal sweep","quantile regression outputs can cross because monotonicity is not enforced here"],"cost":{"model_load_seconds":load,"experiment_seconds":exp,"total_script_seconds":time.perf_counter()-started,"peak_rss_mib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.0},"provenance":{"run_id":os.getenv("GITHUB_RUN_ID","local"),"code_revision":git,"model_revision":REV,"tokenizer_revision":None,"environment":{"python":sys.version.split()[0],"platform":platform.platform(),"numpy":np.__version__,"torch":torch.__version__,"chronos_forecasting":importlib.metadata.version("chronos-forecasting")},"randomness":{"deterministic_forecast":True},"raw_input_hash":hjson({"amplitude":AMPLITUDE,"lags":LAGS,"context_length":CONTEXT_LENGTH,"horizon":HORIZON}),"raw_output_hash":raw}}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(bundle,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"output":str(a.output),"positions":len(rows),"repeat_exact":derived["same_batch_repeat_exact"],"terminal_ratio":derived["terminal_to_max_nonterminal_magnitude_ratio"],"crossing_positions":derived["quantile_crossing_positions"],"science_seconds":exp},sort_keys=True)); return 0
if __name__=="__main__":raise SystemExit(main())
