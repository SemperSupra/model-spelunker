#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, importlib.metadata, json, math, os, platform, resource, sys, time
from pathlib import Path
from typing import Any
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio, pad_or_trim

LOGICAL_ID="asr/faster-whisper/tiny"
REV="d90ca5fe260221311c53c58e660288d3deb8d356"
DIGEST="sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
FIXTURE_SHA="sha256:63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715"
SILENCES=[0.25,0.5,1.0,2.0]
SR=16000


def hbytes(b:bytes)->str:return "sha256:"+hashlib.sha256(b).hexdigest()
def hjson(v:Any)->str:return hbytes(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode())
def ah(x:np.ndarray)->str:return hbytes(np.ascontiguousarray(x,dtype=np.float32).tobytes())

def frame_metrics(a:np.ndarray,b:np.ndarray)->dict[str,float]:
    a=np.asarray(a,dtype=np.float64); b=np.asarray(b,dtype=np.float64)
    an=np.linalg.norm(a,axis=-1); bn=np.linalg.norm(b,axis=-1); den=an*bn; dots=np.sum(a*b,axis=-1)
    cos=np.ones(len(a)); nz=den>1e-12; cos[nz]=dots[nz]/den[nz]
    cos[~nz]=np.where(np.linalg.norm(a[~nz]-b[~nz],axis=-1)<=1e-12,1.0,0.0)
    d=1.0-cos
    return {"mean_cosine_distance":float(np.mean(d)),"median_cosine_distance":float(np.median(d)),"relative_frobenius_difference":float(np.linalg.norm(a-b)/max(float(np.linalg.norm(a)),1e-12))}

def compare_at_offset(ref:np.ndarray,cand:np.ndarray,offset:int,trim:int=0)->dict[str,Any]:
    if offset<0 or offset>=len(cand): raise ValueError(offset)
    n=min(len(ref),len(cand)-offset); a=ref[:n]; b=cand[offset:offset+n]
    if trim and n>2*trim: a=a[trim:-trim]; b=b[trim:-trim]
    out=frame_metrics(a,b); out.update({"offset_frames":offset,"common_frames":len(a),"trim_each_edge":trim}); return out

def search_offsets(ref:np.ndarray,cand:np.ndarray,expected:int,radius:int,trim:int=0)->dict[str,Any]:
    tested=[]
    for off in range(max(0,expected-radius),min(len(cand)-1,expected+radius)+1): tested.append(compare_at_offset(ref,cand,off,trim))
    best=min(tested,key=lambda x:x["mean_cosine_distance"])
    return {"expected_offset_frames":expected,"radius":radius,"best":best,"expected":next(x for x in tested if x["offset_frames"]==expected),"tested":tested}

def bins(ref:np.ndarray,cand:np.ndarray,offset:int)->dict[str,float]:
    n=min(len(ref),len(cand)-offset); a=ref[:n]; b=cand[offset:offset+n]; edges=[0,n//3,2*n//3,n]; out={}
    for name,(s,e) in zip(("early","middle","late"),zip(edges[:-1],edges[1:])): out[name]=frame_metrics(a[s:e],b[s:e])["mean_cosine_distance"]
    return out

def encode(model:WhisperModel,audio:np.ndarray)->dict[str,Any]:
    f=np.asarray(model.feature_extractor(audio),dtype=np.float32); used=min(f.shape[-1],model.feature_extractor.nb_max_frames); fu=f[:,:used]
    fp=np.asarray(pad_or_trim(fu,length=3000),dtype=np.float32); enc=np.asarray(model.encode(fp),dtype=np.float32)
    if enc.ndim==2: enc=enc[None,...]
    ratio=enc.shape[1]/3000.0; active=max(1,min(enc.shape[1],int(math.ceil(used*ratio))))
    return {"feature":fu.T,"encoder":enc[0,:active,:],"feature_frames":int(used),"encoder_frames":int(active),"ratio":float(ratio),"encoder_hash":ah(enc)}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--model-dir",type=Path,required=True); p.add_argument("--fixture",type=Path,required=True); p.add_argument("--fixture-meta",type=Path,required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    os.environ["HF_HUB_OFFLINE"]="1"; os.environ["TRANSFORMERS_OFFLINE"]="1"; start=time.perf_counter()
    meta=json.loads(a.fixture_meta.read_text()); assert hbytes(a.fixture.read_bytes())==FIXTURE_SHA==meta["sha256"]
    audio=decode_audio(str(a.fixture),sampling_rate=SR).astype(np.float32)
    t=time.perf_counter(); model=WhisperModel(str(a.model_dir),device="cpu",compute_type="int8",local_files_only=True); load=time.perf_counter()-t
    t=time.perf_counter(); base=encode(model,audio); repeat=encode(model,audio); rows=[]
    for seconds in SILENCES:
        cand=encode(model,np.concatenate([np.zeros(int(round(seconds*SR)),dtype=np.float32),audio]))
        fexp=int(round(seconds/model.feature_extractor.time_per_frame)); eexp=int(round(fexp*cand["ratio"]))
        fs=search_offsets(base["feature"],cand["feature"],fexp,2,0)
        es=search_offsets(base["encoder"],cand["encoder"],eexp,6,0)
        interior=search_offsets(base["encoder"],cand["encoder"],eexp,6,32)
        bestoff=es["best"]["offset_frames"]
        rows.append({"silence_seconds":seconds,"feature_expected_offset_frames":fexp,"encoder_expected_offset_frames":eexp,"feature_search":fs,"encoder_search_full":es,"encoder_search_interior_trim32":interior,"best_offset_position_bins":bins(base["encoder"],cand["encoder"],bestoff),"candidate_feature_frames":cand["feature_frames"],"candidate_encoder_frames":cand["encoder_frames"]})
    exp=time.perf_counter()-t
    derived={"baseline_repeat_encoder_hash_equal":repeat["encoder_hash"]==base["encoder_hash"],"all_feature_best_offsets_equal_expected":all(r["feature_search"]["best"]["offset_frames"]==r["feature_expected_offset_frames"] for r in rows),"feature_best_mean_cosine_distances":[r["feature_search"]["best"]["mean_cosine_distance"] for r in rows],"encoder_best_offset_deltas":[r["encoder_search_full"]["best"]["offset_frames"]-r["encoder_expected_offset_frames"] for r in rows],"encoder_best_mean_cosine_distances":[r["encoder_search_full"]["best"]["mean_cosine_distance"] for r in rows],"encoder_expected_mean_cosine_distances":[r["encoder_search_full"]["expected"]["mean_cosine_distance"] for r in rows],"encoder_interior_best_mean_cosine_distances":[r["encoder_search_interior_trim32"]["best"]["mean_cosine_distance"] for r in rows]}
    obs={"fixture":meta,"protocol":{"sample_rate":SR,"feature_offset_search_radius":2,"encoder_offset_search_radius":6,"interior_trim_encoder_frames_each_edge":32,"reference_architecture":{"repository":"openai/whisper","source_revision":"86098128c0b4f24f0e2aa2994de830614b474227","observed_properties":["audio encoder conv2 stride=2","fixed sinusoidal positional embedding added after convolution"]}},"baseline":{"feature_frames":base["feature_frames"],"encoder_frames":base["encoder_frames"],"encoder_hash":base["encoder_hash"]},"silence_shift_rows":rows}
    git=os.getenv("GITHUB_SHA"); bundle={"probe_id":"audio-shift-equivariance-faster-whisper-tiny-v1","instrument":"audio-known-shift-offset-search-suite","instrument_version":"mvp-1","model_identity":{"repository":"Systran/faster-whisper-tiny","revision":REV,"logical_id":LOGICAL_ID,"model_class":"speech-to-text-asr-encoder-decoder"},"artifact_provenance":{"tracked":True,"foundry_repository":"SemperSupra/model-artifact-foundry","logical_artifact_id":LOGICAL_ID,"upstream_provider":"huggingface","upstream_repository":"Systran/faster-whisper-tiny","upstream_revision":REV,"identity_kind":"oci","identity_digest":DIGEST,"foundry_record_ref":"SemperSupra/model-artifact-foundry@6622753fd5914be87fb1b6d987ceb7cae46c7ff5:catalog/approved.json","consumer_selection_ref":f"model-spelunker@{git}" if git else None,"verified":True,"verification_ref":"digest-pinned approved Foundry hydration with offline local reuse","tokenizer_artifact":None},"access_tier":"A2","evidence_level":"RELATIONAL","claim_tags":["AUDIO","TEMPORAL_SHIFT","REPRESENTATION_GEOMETRY","INVARIANT_TEST"],"observations":obs,"derived_metrics":derived,"uncertainty":{"architecture_mapping":"reference OpenAI Whisper encoder source supports interpretation but is not itself proof of byte-identical converted implementation internals","causality":"offset search distinguishes simple temporal misalignment from persistent representation change; it does not isolate a single causal component"},"known_assumptions":["CTranslate2 conversion preserves the relevant Whisper encoder architecture","known injected silence maps to feature offset using Faster-Whisper time_per_frame"],"known_failure_modes":["best local offset may absorb some representation deformation rather than pure timing error","absolute-position and self-attention effects are not separately intervened on"],"cost":{"model_load_seconds":load,"experiment_seconds":exp,"total_script_seconds":time.perf_counter()-start,"peak_rss_mib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.0},"provenance":{"run_id":os.getenv("GITHUB_RUN_ID","local"),"code_revision":git,"model_revision":REV,"tokenizer_revision":REV,"environment":{"python":sys.version.split()[0],"platform":platform.platform(),"numpy":np.__version__,"faster_whisper":importlib.metadata.version("faster-whisper"),"ctranslate2":importlib.metadata.version("ctranslate2")},"randomness":{},"raw_input_hash":hjson({"fixture":meta,"silences":SILENCES,"feature_radius":2,"encoder_radius":6}),"raw_output_hash":hjson({"observations":obs,"derived_metrics":derived})}}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(bundle,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"output":str(a.output),"feature_exact":derived["all_feature_best_offsets_equal_expected"],"encoder_offset_deltas":derived["encoder_best_offset_deltas"],"encoder_best":derived["encoder_best_mean_cosine_distances"],"repeat":derived["baseline_repeat_encoder_hash_equal"]},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
