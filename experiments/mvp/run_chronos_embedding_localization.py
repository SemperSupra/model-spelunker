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
AMPS=[0.5,1.0,2.0,5.0,10.0]


def hbytes(b:bytes)->str:return "sha256:"+hashlib.sha256(b).hexdigest()
def hjson(v:Any)->str:return hbytes(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode())
def th(x:torch.Tensor)->str:return hbytes(x.detach().cpu().to(torch.float32).contiguous().numpy().tobytes())
def cosine(a:torch.Tensor,b:torch.Tensor)->float:
    x=a.detach().cpu().to(torch.float64).reshape(-1);y=b.detach().cpu().to(torch.float64).reshape(-1);den=float(torch.linalg.vector_norm(x)*torch.linalg.vector_norm(y));return 0.0 if den<=1e-12 and torch.allclose(x,y) else (1.0 if den<=1e-12 else float(1.0-torch.dot(x,y)/den))
def context(amplitude:float=0.0,lag:int=0)->torch.Tensor:
    x=torch.zeros(CONTEXT_LENGTH,dtype=torch.float32)
    if amplitude!=0.0:x[-1-lag]=amplitude
    return x

def rep_compare(a:torch.Tensor,b:torch.Tensor)->dict[str,float]:
    x=a.detach().cpu().to(torch.float64);y=b.detach().cpu().to(torch.float64);return {"cosine_distance":cosine(x,y),"max_abs_delta":float((x-y).abs().max()),"mean_abs_delta":float((x-y).abs().mean()),"relative_l2_delta":float(torch.linalg.vector_norm(x-y)/max(float(torch.linalg.vector_norm(x)),1e-12))}
def forecast_summary(f:torch.Tensor)->dict[str,Any]:
    f=f.detach().cpu().to(torch.float32);m=f[4];return {"sha256_float32":th(f),"median_abs_mean":float(m.abs().mean()),"median_first":float(m[0]),"median_last":float(m[-1]),"quantile_crossing_cells":int((f[:-1]>f[1:]).sum()),"finite":bool(torch.isfinite(f).all())}

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--model-dir',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--candidate-ref',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';started=time.perf_counter();c=json.loads(a.candidate.read_text());assert c['logical_id']==LOGICAL_ID and c['upstream']['exact_revision']==REV and c['oci']['pullback_verified'];digest=c['oci']['digest']
    t=time.perf_counter();pipe=BaseChronosPipeline.from_pretrained(str(a.model_dir),device_map='cpu',torch_dtype=torch.float32,local_files_only=True);load=time.perf_counter()-t
    if not isinstance(pipe,ChronosBoltPipeline):raise RuntimeError(type(pipe).__name__)
    cfg=pipe.model.chronos_config;patch_size=int(cfg.input_patch_size);patch_stride=int(cfg.input_patch_stride);use_reg=bool(cfg.use_reg_token)
    specs=[('zero',0.0,0)]+[(f'terminal_pos_{A:g}',A,0) for A in AMPS]+[('terminal_neg5',-5.0,0),('lag1_pos5',5.0,1),('lag15_pos5',5.0,15),('lag16_pos5',5.0,16),('lag32_pos5',5.0,32)]
    contexts=[context(A,lag) for _,A,lag in specs]
    t=time.perf_counter()
    with torch.inference_mode():
        emb,(loc,scale)=pipe.embed(contexts)
        forecasts=pipe.predict(contexts,prediction_length=HORIZON,limit_prediction_length=True).float().cpu()
        emb2,(loc2,scale2)=pipe.embed(contexts)
    exp=time.perf_counter()-t
    emb=emb.float().cpu();emb2=emb2.float().cpu();loc=loc.float().cpu();scale=scale.float().cpu();loc2=loc2.float().cpu();scale2=scale2.float().cpu()
    if emb.ndim!=3 or emb.shape[0]!=len(specs):raise RuntimeError(emb.shape)
    data_patch_count=CONTEXT_LENGTH//patch_size;expected_seq=data_patch_count+(1 if use_reg else 0)
    if emb.shape[1]!=expected_seq:raise RuntimeError((emb.shape,expected_seq,use_reg))
    ref_i=next(i for i,s in enumerate(specs) if s[0]=='terminal_pos_5');ref=emb[ref_i];ref_forecast=forecasts[ref_i]
    rows=[]
    for i,(name,A,lag) in enumerate(specs):
        patch_idx=(CONTEXT_LENGTH-1-lag)//patch_size if A!=0 else None;offset=(CONTEXT_LENGTH-1-lag)%patch_size if A!=0 else None
        per_patch=[rep_compare(ref[j],emb[i,j]) for j in range(data_patch_count)]
        rows.append({"id":name,"amplitude":A,"lag_from_end":lag if A!=0 else None,"patch_index":patch_idx,"offset_within_patch":offset,"loc":float(loc[i]),"scale":float(scale[i]),"embedding":{"shape":list(emb[i].shape),"sha256_float32":th(emb[i]),"full_vs_terminal_pos5":rep_compare(ref,emb[i]),"data_patch_vs_terminal_pos5":per_patch,"final_data_patch_vs_terminal_pos5":per_patch[-1],"reg_token_vs_terminal_pos5":rep_compare(ref[-1],emb[i,-1]) if use_reg else None},"forecast":forecast_summary(forecasts[i]),"forecast_vs_terminal_pos5":rep_compare(ref_forecast,forecasts[i]),"repeat":{"embedding_hash_equal":th(emb[i])==th(emb2[i]),"embedding_max_abs_delta":float((emb[i]-emb2[i]).abs().max()),"loc_equal":bool(loc[i].item()==loc2[i].item()),"scale_equal":bool(scale[i].item()==scale2[i].item())}})
    positive=[r for r in rows if r['id'].startswith('terminal_pos_')]
    positive_ref=next(r for r in positive if r['amplitude']==5.0)
    amp_embedding_max=max(r['embedding']['full_vs_terminal_pos5']['max_abs_delta'] for r in positive)
    amp_embedding_cos=max(r['embedding']['full_vs_terminal_pos5']['cosine_distance'] for r in positive)
    restored_forecast=[]
    for r in positive:
        i=next(i for i,s in enumerate(specs) if s[0]==r['id']);restored=forecasts[i]*(5.0/r['amplitude']);restored_forecast.append(float((restored-ref_forecast).abs().max()))
    observations={"protocol":{"context_length":CONTEXT_LENGTH,"prediction_length":HORIZON,"patch_size":patch_size,"patch_stride":patch_stride,"use_reg_token":use_reg,"data_patch_count":data_patch_count,"embedding_sequence_length":int(emb.shape[1]),"embedding_dimension":int(emb.shape[2]),"public_api":"ChronosBoltPipeline.embed","full_embedding_tensors_persisted":False},"conditions":rows}
    byid={r['id']:r for r in rows}
    derived={"positive_amplitude_embedding_max_abs_delta":amp_embedding_max,"positive_amplitude_embedding_max_cosine_distance":amp_embedding_cos,"positive_amplitude_forecast_rescaled_max_abs_delta":max(restored_forecast),"positive_amplitude_loc_per_unit":[r['loc']/r['amplitude'] for r in positive],"positive_amplitude_scale_per_unit":[r['scale']/r['amplitude'] for r in positive],"terminal_sign_embedding_cosine_distance":byid['terminal_neg5']['embedding']['full_vs_terminal_pos5']['cosine_distance'],"lag1_embedding_cosine_distance":byid['lag1_pos5']['embedding']['full_vs_terminal_pos5']['cosine_distance'],"lag15_embedding_cosine_distance":byid['lag15_pos5']['embedding']['full_vs_terminal_pos5']['cosine_distance'],"lag16_embedding_cosine_distance":byid['lag16_pos5']['embedding']['full_vs_terminal_pos5']['cosine_distance'],"lag32_embedding_cosine_distance":byid['lag32_pos5']['embedding']['full_vs_terminal_pos5']['cosine_distance'],"lag1_final_patch_embedding_cosine_distance":byid['lag1_pos5']['embedding']['final_data_patch_vs_terminal_pos5']['cosine_distance'],"lag16_final_patch_embedding_cosine_distance":byid['lag16_pos5']['embedding']['final_data_patch_vs_terminal_pos5']['cosine_distance'],"all_embedding_repeats_exact":all(r['repeat']['embedding_hash_equal'] and r['repeat']['loc_equal'] and r['repeat']['scale_equal'] for r in rows),"all_outputs_finite":bool(torch.isfinite(emb).all() and torch.isfinite(forecasts).all())}
    raw=hjson({'observations':observations,'derived_metrics':derived});git=os.getenv('GITHUB_SHA')
    bundle={"probe_id":"chronos-bolt-embedding-localization-v1","instrument":"timeseries-public-encoder-embedding-localization-suite","instrument_version":"mvp-1","model_identity":{"repository":UPSTREAM_REPO,"revision":REV,"logical_id":LOGICAL_ID,"model_class":"time-series-probabilistic-forecaster"},"artifact_provenance":{"tracked":True,"foundry_repository":"SemperSupra/model-artifact-foundry","logical_artifact_id":LOGICAL_ID,"upstream_provider":"huggingface","upstream_repository":UPSTREAM_REPO,"upstream_revision":REV,"identity_kind":"oci","identity_digest":digest,"foundry_record_ref":a.candidate_ref,"consumer_selection_ref":f"model-spelunker@{git}" if git else None,"verified":True,"verification_ref":"pullback-verified candidate Foundry hydration with forced-offline local reuse","tokenizer_artifact":None},"access_tier":"A2","evidence_level":"RELATIONAL","claim_tags":["TIME_SERIES","ENCODER_REPRESENTATION","INSTANCE_NORMALIZATION","SCALE_INVARIANCE","POSITION_SENSITIVITY","SIGN_ASYMMETRY"],"observations":observations,"derived_metrics":derived,"uncertainty":{"scope":"public final encoder embeddings and loc/scale only; no per-layer or causal intervention","normalization_attribution":"architectural source places instance normalization before patching/encoder and inverse scaling after output, but this rep remains observational","zero_context":"zero context uses the model epsilon scale path and is a control rather than a natural-data baseline"},"known_assumptions":["public ChronosBoltPipeline.embed follows the same model.encode path used by forecasting","positive one-hot amplitudes share the same standardized pattern under instance normalization","identical loc/scale for equal-amplitude impulses at different positions isolates downstream position processing from global normalization statistics"],"known_failure_modes":["final encoder embedding differences do not localize which encoder layer creates the effect","synthetic zero-baseline impulses are out-of-distribution for many real series","decoder/output head may amplify or suppress encoder differences nonlinearly"],"cost":{"model_load_seconds":load,"experiment_seconds":exp,"total_script_seconds":time.perf_counter()-started,"peak_rss_mib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.0},"provenance":{"run_id":os.getenv('GITHUB_RUN_ID','local'),"code_revision":git,"model_revision":REV,"tokenizer_revision":None,"environment":{"python":sys.version.split()[0],"platform":platform.platform(),"numpy":np.__version__,"torch":torch.__version__,"chronos_forecasting":importlib.metadata.version('chronos-forecasting')},"randomness":{"deterministic_forecast":True},"raw_input_hash":hjson({'conditions':specs,'context_length':CONTEXT_LENGTH,'horizon':HORIZON}),"raw_output_hash":raw}}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(bundle,indent=2,sort_keys=True)+'\n')
    print(json.dumps({"output":str(a.output),"embedding_shape":list(emb.shape),"positive_amp_embedding_max_delta":amp_embedding_max,"positive_amp_rescaled_forecast_max":derived['positive_amplitude_forecast_rescaled_max_abs_delta'],"lag1_embedding_cosine":derived['lag1_embedding_cosine_distance'],"sign_embedding_cosine":derived['terminal_sign_embedding_cosine_distance'],"repeat_exact":derived['all_embedding_repeats_exact']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
