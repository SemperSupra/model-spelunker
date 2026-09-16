#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, importlib.metadata, json, math, os, platform, resource, sys, time, unicodedata
from pathlib import Path
from typing import Any
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio, pad_or_trim

LOGICAL_ID="asr/faster-whisper/tiny"
UPSTREAM_REPO="Systran/faster-whisper-tiny"
UPSTREAM_REVISION="d90ca5fe260221311c53c58e660288d3deb8d356"
FOUNDRY_DIGEST="sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
FOUNDRY_CATALOG_REF="SemperSupra/model-artifact-foundry@6622753fd5914be87fb1b6d987ceb7cae46c7ff5:catalog/approved.json"
DATASET_REPO="facebook/multilingual_librispeech"
DATASET_REVISION="2e83e61823b4c47dcbcb1980bb88601274127609"
SAMPLE_RATE=16000
ENCODER_INPUT_FRAMES=3000
CONDITIONS=("baseline","snr_20db","snr_10db")


def sha256_bytes(b:bytes)->str:return "sha256:"+hashlib.sha256(b).hexdigest()
def sha256_json(v:Any)->str:return sha256_bytes(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode())
def array_hash(x:np.ndarray)->str:return sha256_bytes(np.ascontiguousarray(x).tobytes(order="C"))
def rms(x:np.ndarray)->float:
    a=np.asarray(x,dtype=np.float64); return float(np.sqrt(np.mean(a*a))) if a.size else 0.0

def normchars(s:str)->list[str]:
    t=unicodedata.normalize("NFKC",s).casefold(); return [c for c in t if not c.isspace() and (c.isalnum() or unicodedata.category(c).startswith("L"))]
def edit(a:list[str],b:list[str])->int:
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        cur=[i]
        for j,y in enumerate(b,1):cur.append(min(cur[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=cur
    return prev[-1]
def cer(ref:str,cand:str)->dict[str,Any]:
    a,b=normchars(ref),normchars(cand); e=edit(a,b); return {"reference_chars":len(a),"candidate_chars":len(b),"char_edit_distance":e,"normalized_char_edit_distance":float(e/max(1,len(a)))}
def cosdist(a:np.ndarray,b:np.ndarray)->float:
    x=np.asarray(a,dtype=np.float64).reshape(-1); y=np.asarray(b,dtype=np.float64).reshape(-1); d=float(np.linalg.norm(x)*np.linalg.norm(y))
    return (0.0 if np.allclose(x,y) else 1.0) if d<=1e-12 else float(1.0-np.dot(x,y)/d)
def frame_dist(a:np.ndarray,b:np.ndarray)->float:
    n=min(a.shape[0],b.shape[0]); aa=np.asarray(a[:n],dtype=np.float64); bb=np.asarray(b[:n],dtype=np.float64); den=np.linalg.norm(aa,axis=-1)*np.linalg.norm(bb,axis=-1); dots=np.sum(aa*bb,axis=-1); c=np.ones(n); nz=den>1e-12; c[nz]=dots[nz]/den[nz]; c[~nz]=np.where(np.linalg.norm(aa[~nz]-bb[~nz],axis=-1)<=1e-12,1.0,0.0); return float(np.mean(1.0-c))

def encode(model:WhisperModel,audio:np.ndarray)->dict[str,Any]:
    f=model.feature_extractor(audio); used=min(int(f.shape[-1]),int(model.feature_extractor.nb_max_frames)); p=np.asarray(pad_or_trim(np.asarray(f[:,:used],dtype=np.float32),length=ENCODER_INPUT_FRAMES),dtype=np.float32); e=np.asarray(model.encode(p)); e=e[np.newaxis,...] if e.ndim==2 else e; e=np.asarray(e,dtype=np.float32); ratio=e.shape[1]/float(ENCODER_INPUT_FRAMES); active=e[0,:max(1,min(e.shape[1],int(math.ceil(used*ratio)))),:]; return {"active":active,"pooled":active.mean(axis=0),"hash":array_hash(e),"shape":list(e.shape)}
def transcribe(model:WhisperModel,audio:np.ndarray)->dict[str,Any]:
    segs,info=model.transcribe(audio,language=None,beam_size=1,temperature=0.0,condition_on_previous_text=False,vad_filter=False,word_timestamps=False); rows=[{"text":str(s.text),"avg_logprob":float(s.avg_logprob),"no_speech_prob":float(s.no_speech_prob)} for s in segs]; text="".join(x["text"] for x in rows).strip(); return {"transcript":text,"detected_language":str(info.language),"language_probability":float(info.language_probability),"segment_count":len(rows),"mean_avg_logprob":float(np.mean([x["avg_logprob"] for x in rows])) if rows else None,"max_no_speech_prob":max([x["no_speech_prob"] for x in rows],default=None)}
def noise(audio:np.ndarray,db:float,sample_id:str)->np.ndarray:
    seed=int(hashlib.sha256(sample_id.encode()).hexdigest()[:8],16); r=np.random.default_rng(seed); n=r.standard_normal(audio.shape,dtype=np.float32); n/=max(rms(n),1e-8); target=max(rms(audio),1e-8)/(10.0**(db/20.0)); return np.clip(audio+n*target,-1,1).astype(np.float32)
def perturb(audio:np.ndarray,c:str,sample_id:str)->np.ndarray:
    if c=="baseline":return audio.copy()
    if c=="snr_20db":return noise(audio,20.0,sample_id)
    if c=="snr_10db":return noise(audio,10.0,sample_id)
    raise KeyError(c)

def stats(v:list[float])->dict[str,float]:
    a=np.asarray(v,dtype=np.float64); return {"mean":float(np.mean(a)),"std":float(np.std(a)),"min":float(np.min(a)),"max":float(np.max(a)),"variance":float(np.var(a))}
def variance_partition(groups:dict[str,list[float]])->dict[str,Any]:
    means={k:float(np.mean(v)) for k,v in groups.items()}; within={k:float(np.var(v)) for k,v in groups.items()}; between=float(np.var(list(means.values()))); mean_within=float(np.mean(list(within.values()))); denom=between+mean_within
    return {"speaker_means":means,"within_speaker_variances":within,"between_speaker_mean_variance":between,"mean_within_speaker_utterance_variance":mean_within,"descriptive_between_fraction":float(between/denom) if denom>0 else 0.0}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--model-dir",type=Path,required=True); p.add_argument("--samples-dir",type=Path,required=True); p.add_argument("--panel",type=Path,required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    os.environ["HF_HUB_OFFLINE"]="1"; os.environ["TRANSFORMERS_OFFLINE"]="1"; started=time.perf_counter(); panel=json.loads(a.panel.read_text())
    if panel["dataset_repository"]!=DATASET_REPO or panel["dataset_revision"]!=DATASET_REVISION:raise RuntimeError("dataset identity mismatch")
    t=time.perf_counter(); model=WhisperModel(str(a.model_dir),device="cpu",compute_type="int8",local_files_only=True); load=time.perf_counter()-t; t=time.perf_counter(); langs=[]
    for lang in panel["languages"]:
        speakers=[]
        for sp in lang["speakers"]:
            utterances=[]
            for spec in sp["utterances"]:
                raw=decode_audio(str(a.samples_dir/spec["local_file"]),sampling_rate=SAMPLE_RATE).astype(np.float32); be=encode(model,raw); ba=transcribe(model,raw); conds=[]
                for c in CONDITIONS:
                    x=perturb(raw,c,spec["sample_id"]); e=be if c=="baseline" else encode(model,x); d=ba if c=="baseline" else transcribe(model,x)
                    conds.append({"condition":c,"audio_sha256_float32le":array_hash(np.asarray(x,dtype="<f4")),"representation":{"encoder_shape":e["shape"],"encoder_hash":e["hash"],"pooled_cosine_distance_from_baseline":cosdist(be["pooled"],e["pooled"]),"frame_cosine_distance_from_baseline":frame_dist(be["active"],e["active"])},"decoder":{**d,"ground_truth_char_error":cer(spec["transcript"],d["transcript"]),"relative_to_baseline_char_error":cer(ba["transcript"],d["transcript"]),"language_matches_expected":d["detected_language"]==lang["expected_language"]}})
                re=encode(model,raw); ra=transcribe(model,raw)
                utterances.append({"utterance_index":spec["utterance_index"],"sample_id":spec["sample_id"],"chapter_id":spec["chapter_id"],"source_row_index":spec["source_row_index"],"source_audio_sha256":spec["audio_sha256"],"ground_truth_transcript":spec["transcript"],"conditions":conds,"baseline_repeat":{"encoder_hash_equal":re["hash"]==be["hash"],"transcript_equal":ra["transcript"]==ba["transcript"],"language_equal":ra["detected_language"]==ba["detected_language"]}})
            speakers.append({"speaker_id":sp["speaker_id"],"utterances":utterances})
        langs.append({"config":lang["config"],"expected_language":lang["expected_language"],"source_parquet_path":lang["source_parquet_path"],"source_parquet_sha256":lang["source_parquet_sha256"],"speakers":speakers})
    science=time.perf_counter()-t
    per_lang={}; all_utts=[]
    for lang in langs:
        summary={}
        for c in CONDITIONS:
            gt_groups={}; rel_groups={}; frame_groups={}
            for sp in lang["speakers"]:
                rs=[next(x for x in u["conditions"] if x["condition"]==c) for u in sp["utterances"]]; gt_groups[sp["speaker_id"]]=[r["decoder"]["ground_truth_char_error"]["normalized_char_edit_distance"] for r in rs]; rel_groups[sp["speaker_id"]]=[r["decoder"]["relative_to_baseline_char_error"]["normalized_char_edit_distance"] for r in rs]; frame_groups[sp["speaker_id"]]=[r["representation"]["frame_cosine_distance_from_baseline"] for r in rs]
            flatgt=sum(gt_groups.values(),[]); flatrel=sum(rel_groups.values(),[]); flatframe=sum(frame_groups.values(),[])
            summary[c]={"ground_truth_cer":stats(flatgt),"relative_to_baseline_cer":stats(flatrel),"frame_cosine_distance":stats(flatframe),"ground_truth_variance_partition":variance_partition(gt_groups),"relative_cer_variance_partition":variance_partition(rel_groups),"frame_variance_partition":variance_partition(frame_groups)}
        per_lang[lang["config"]]={"speaker_ids":[s["speaker_id"] for s in lang["speakers"]],"conditions":summary}
        all_utts += [u for s in lang["speakers"] for u in s["utterances"]]
    obs={"dataset":{"repository":panel["dataset_repository"],"revision":panel["dataset_revision"],"license_spdx":panel["license_spdx"],"split":panel["split"],"selection_rule":panel["selection_rule"],"speaker_freeze_provenance":panel["speaker_freeze_provenance"]},"protocol":{"conditions":list(CONDITIONS),"utterances_per_speaker":3,"speakers_per_language":3,"language_mode":"auto-detect","full_encoder_tensor_persisted":False},"languages":langs}
    derived={"language_count":3,"speaker_count":9,"utterance_count":27,"all_baseline_encoder_repeats_exact":all(u["baseline_repeat"]["encoder_hash_equal"] for u in all_utts),"all_baseline_transcript_repeats_exact":all(u["baseline_repeat"]["transcript_equal"] for u in all_utts),"all_baseline_language_repeats_exact":all(u["baseline_repeat"]["language_equal"] for u in all_utts),"per_language":per_lang}
    git=os.environ.get("GITHUB_SHA"); run=os.environ.get("GITHUB_RUN_ID","local"); out_hash=sha256_json({"observations":obs,"derived_metrics":derived})
    bundle={"probe_id":"audio-repeated-speaker-variance-faster-whisper-tiny-v1","instrument":"audio-repeated-speaker-utterance-variance-suite","instrument_version":"mvp-1","model_identity":{"repository":UPSTREAM_REPO,"revision":UPSTREAM_REVISION,"logical_id":LOGICAL_ID,"model_class":"speech-to-text-asr-encoder-decoder"},"artifact_provenance":{"tracked":True,"foundry_repository":"SemperSupra/model-artifact-foundry","logical_artifact_id":LOGICAL_ID,"upstream_provider":"huggingface","upstream_repository":UPSTREAM_REPO,"upstream_revision":UPSTREAM_REVISION,"identity_kind":"oci","identity_digest":FOUNDRY_DIGEST,"foundry_record_ref":FOUNDRY_CATALOG_REF,"consumer_selection_ref":f"model-spelunker@{git}" if git else None,"verified":True,"verification_ref":"digest-pinned approved Foundry hydration with offline local reuse","tokenizer_artifact":None},"access_tier":"A2","evidence_level":"REPRODUCED","claim_tags":["AUDIO","SPEAKER_VARIATION","UTTERANCE_VARIATION","VARIANCE_DECOMPOSITION","GROUND_TRUTH"],"observations":obs,"derived_metrics":derived,"uncertainty":{"variance_partition":"descriptive balanced-panel variance of speaker means versus mean within-speaker utterance variance; not an inferential random-effects estimate or ICC","population":"3 languages x 3 frozen speakers x 3 deterministic utterances; audiobook read speech only","speaker_identity":"speaker_id distinguishes corpus speakers; no demographic attributes are inferred"},"known_assumptions":["three utterances per frozen speaker are sufficient for a reconnaissance within-speaker variance estimate","Unicode character error is a useful cross-language scalar surface","same deterministic noise realization per utterance across 20/10 dB preserves dose comparability"],"known_failure_modes":["chapter/content variation remains part of within-speaker utterance variance","small balanced panel cannot estimate population variance components","Tiny Whisper model size can dominate baseline error"],"cost":{"model_load_seconds":load,"experiment_seconds":science,"total_script_seconds":time.perf_counter()-started,"peak_rss_mib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.0},"provenance":{"run_id":str(run),"code_revision":git,"model_revision":UPSTREAM_REVISION,"tokenizer_revision":UPSTREAM_REVISION,"environment":{"python":sys.version.split()[0],"platform":platform.platform(),"numpy":np.__version__,"faster_whisper":importlib.metadata.version("faster-whisper"),"ctranslate2":importlib.metadata.version("ctranslate2")},"randomness":{"noise_seed_rule":"sha256(sample_id)[0:8]","beam_size":1,"temperature":0.0},"raw_input_hash":sha256_json(panel),"raw_output_hash":out_hash}}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(bundle,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"languages":3,"speakers":9,"utterances":27,"conditions":81,"science_seconds":science,"peak_rss_mib":bundle["cost"]["peak_rss_mib"],"all_repeats_exact":derived["all_baseline_encoder_repeats_exact"] and derived["all_baseline_transcript_repeats_exact"]},sort_keys=True)); return 0
if __name__=="__main__":raise SystemExit(main())
