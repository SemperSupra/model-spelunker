#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, importlib.metadata, json, math, os, platform, resource, sys, time, unicodedata
from pathlib import Path
from typing import Any

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio, pad_or_trim

LOGICAL_ID = "asr/faster-whisper/tiny"
UPSTREAM_REPO = "Systran/faster-whisper-tiny"
UPSTREAM_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
FOUNDRY_DIGEST = "sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
FOUNDRY_CATALOG_REF = "SemperSupra/model-artifact-foundry@6622753fd5914be87fb1b6d987ceb7cae46c7ff5:catalog/approved.json"
SAMPLE_RATE = 16000
ENCODER_INPUT_FRAMES = 3000
CONDITIONS = ("baseline", "gain_0.125", "snr_20db", "snr_10db", "silence_500ms")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def array_hash(x: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(x).tobytes(order="C"))


def rms(x: np.ndarray) -> float:
    a = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(a*a))) if a.size else 0.0


def normalize_chars(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text).casefold()
    return [c for c in t if not c.isspace() and (c.isalnum() or unicodedata.category(c).startswith("L"))]


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b)+1))
    for i,x in enumerate(a,1):
        cur=[i]
        for j,y in enumerate(b,1):
            cur.append(min(cur[-1]+1, prev[j]+1, prev[j-1]+(x!=y)))
        prev=cur
    return prev[-1]


def char_distance(ref: str, cand: str) -> dict[str, Any]:
    a,b=normalize_chars(ref),normalize_chars(cand)
    e=edit_distance(a,b)
    return {"reference_chars":len(a),"candidate_chars":len(b),"char_edit_distance":e,"normalized_char_edit_distance":float(e/max(1,len(a)))}


def cosine_distance(a: np.ndarray,b: np.ndarray)->float:
    x=np.asarray(a,dtype=np.float64).reshape(-1); y=np.asarray(b,dtype=np.float64).reshape(-1)
    den=float(np.linalg.norm(x)*np.linalg.norm(y))
    if den<=1e-12: return 0.0 if np.allclose(x,y) else 1.0
    return float(1.0-np.dot(x,y)/den)


def frame_compare(a: np.ndarray,b: np.ndarray,offset:int=0)->dict[str,Any]:
    n=min(a.shape[0], b.shape[0]-offset)
    aa=np.asarray(a[:n],dtype=np.float64); bb=np.asarray(b[offset:offset+n],dtype=np.float64)
    an=np.linalg.norm(aa,axis=-1); bn=np.linalg.norm(bb,axis=-1); den=an*bn; dots=np.sum(aa*bb,axis=-1)
    cos=np.ones(n); nz=den>1e-12; cos[nz]=dots[nz]/den[nz]
    cos[~nz]=np.where(np.linalg.norm(aa[~nz]-bb[~nz],axis=-1)<=1e-12,1.0,0.0)
    return {"common_frames":int(n),"candidate_offset_frames":int(offset),"mean_cosine_distance":float(np.mean(1.0-cos)),"relative_frobenius_difference":float(np.linalg.norm(aa-bb)/max(float(np.linalg.norm(aa)),1e-12))}


def encode(model: WhisperModel,audio: np.ndarray)->dict[str,Any]:
    features=model.feature_extractor(audio)
    used=min(int(features.shape[-1]), int(model.feature_extractor.nb_max_frames))
    unp=np.asarray(features[:,:used],dtype=np.float32)
    padded=np.asarray(pad_or_trim(unp,length=ENCODER_INPUT_FRAMES),dtype=np.float32)
    enc=np.asarray(model.encode(padded))
    if enc.ndim==2: enc=enc[np.newaxis,...]
    enc=np.asarray(enc,dtype=np.float32)
    ratio=enc.shape[1]/float(ENCODER_INPUT_FRAMES)
    active_frames=max(1,min(enc.shape[1],int(math.ceil(used*ratio))))
    active=enc[0,:active_frames,:]
    return {"feature":unp,"encoder":enc,"active":active,"pooled":active.mean(axis=0),"summary":{"feature_frames_used":used,"encoder_shape":list(enc.shape),"encoder_hash":array_hash(enc),"active_encoder_frames":active_frames,"temporal_ratio":float(ratio)}}


def transcribe(model: WhisperModel,audio: np.ndarray)->dict[str,Any]:
    segs,info=model.transcribe(audio,language=None,beam_size=1,temperature=0.0,condition_on_previous_text=False,vad_filter=False,word_timestamps=False)
    rows=[]
    for s in segs:
        rows.append({"text":str(s.text),"avg_logprob":float(s.avg_logprob),"no_speech_prob":float(s.no_speech_prob)})
    txt="".join(r["text"] for r in rows).strip()
    return {"transcript":txt,"detected_language":str(info.language),"language_probability":float(info.language_probability),"segment_count":len(rows),"mean_avg_logprob":float(np.mean([r["avg_logprob"] for r in rows])) if rows else None,"max_no_speech_prob":max([r["no_speech_prob"] for r in rows],default=None)}


def perturb(x: np.ndarray,cond: str)->np.ndarray:
    if cond=="baseline": return x.copy()
    if cond=="gain_0.125": return (x*0.125).astype(np.float32)
    if cond.startswith("snr_"):
        db=float(cond.split("_")[1].replace("db","")); rng=np.random.default_rng(0)
        n=rng.standard_normal(x.shape,dtype=np.float32); n/=max(rms(n),1e-8)
        target=max(rms(x),1e-8)/(10.0**(db/20.0)); return np.clip(x+n*target,-1,1).astype(np.float32)
    if cond=="silence_500ms": return np.concatenate([np.zeros(SAMPLE_RATE//2,dtype=np.float32),x])
    raise KeyError(cond)


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--model-dir",type=Path,required=True); ap.add_argument("--samples-dir",type=Path,required=True); ap.add_argument("--panel-manifest",type=Path,required=True); ap.add_argument("--resolved-manifest",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); args=ap.parse_args()
    os.environ["HF_HUB_OFFLINE"]="1"; os.environ["TRANSFORMERS_OFFLINE"]="1"
    started=time.perf_counter(); manifest=json.loads(args.panel_manifest.read_text()); resolved=json.loads(args.resolved_manifest.read_text())
    t=time.perf_counter(); model=WhisperModel(str(args.model_dir),device="cpu",compute_type="int8",local_files_only=True); load_s=time.perf_counter()-t
    t=time.perf_counter(); languages=[]
    for spec in manifest["samples"]:
        sid=spec["id"]; path=args.samples_dir/f"{sid}.wav"; raw=decode_audio(str(path),sampling_rate=SAMPLE_RATE).astype(np.float32)
        base_enc=encode(model,raw); base_asr=transcribe(model,raw)
        rows=[]
        for cond in CONDITIONS:
            audio=perturb(raw,cond); enc=base_enc if cond=="baseline" else encode(model,audio); asr=base_asr if cond=="baseline" else transcribe(model,audio)
            g={"pooled_cosine_distance":cosine_distance(base_enc["pooled"],enc["pooled"]),"unaligned":frame_compare(base_enc["active"],enc["active"]),"shift_aware":None}
            if cond=="silence_500ms":
                foff=int(round(0.5/model.feature_extractor.time_per_frame)); eoff=int(round(foff*enc["summary"]["temporal_ratio"])); g["shift_aware"]={"feature_offset_frames":foff,"encoder_offset_frames":eoff,"encoder":frame_compare(base_enc["active"],enc["active"],eoff)}
            rows.append({"condition":cond,"audio":{"samples":int(audio.size),"duration_seconds":float(audio.size/SAMPLE_RATE),"rms":rms(audio),"sha256_float32le":array_hash(np.asarray(audio,dtype="<f4"))},"representation":{"encoder_shape":enc["summary"]["encoder_shape"],"active_encoder_frames":enc["summary"]["active_encoder_frames"],"encoder_hash":enc["summary"]["encoder_hash"],"geometry_from_baseline":g},"decoder":{**asr,"char_distance_from_baseline":char_distance(base_asr["transcript"],asr["transcript"]),"language_changed_from_baseline":asr["detected_language"]!=base_asr["detected_language"]}})
        rep_enc=encode(model,raw); rep_asr=transcribe(model,raw)
        languages.append({"id":sid,"expected_language":spec["expected_language"],"readme_prefix":spec["readme_prefix"],"source":resolved["samples"][sid],"baseline_expected_language_match":base_asr["detected_language"]==spec["expected_language"],"baseline_readme_prefix_observed":normalize_chars(spec["readme_prefix"])==normalize_chars(base_asr["transcript"])[:len(normalize_chars(spec["readme_prefix"]))],"conditions":rows,"baseline_repeat":{"encoder_hash_equal":rep_enc["summary"]["encoder_hash"]==base_enc["summary"]["encoder_hash"],"transcript_equal":rep_asr["transcript"]==base_asr["transcript"],"detected_language_equal":rep_asr["detected_language"]==base_asr["detected_language"]}})
    science_s=time.perf_counter()-t
    per_language={}
    for lang in languages:
        base=next(r for r in lang["conditions"] if r["condition"]=="baseline")
        summary={}
        for r in lang["conditions"]:
            summary[r["condition"]]={"normalized_char_edit_distance":r["decoder"]["char_distance_from_baseline"]["normalized_char_edit_distance"],"detected_language":r["decoder"]["detected_language"],"language_changed":r["decoder"]["language_changed_from_baseline"],"pooled_cosine_distance":r["representation"]["geometry_from_baseline"]["pooled_cosine_distance"],"frame_cosine_distance":r["representation"]["geometry_from_baseline"]["unaligned"]["mean_cosine_distance"]}
        per_language[lang["id"]]=summary
    detected_baseline_matches=sum(1 for l in languages if l["baseline_expected_language_match"])
    observations={"panel_source":{"repository":manifest["source_repository"],"commit":manifest["source_commit"],"repository_license":manifest["repository_license"],"scope_note":manifest["scope_note"]},"protocol":{"conditions":list(CONDITIONS),"sample_rate":SAMPLE_RATE,"full_encoder_tensor_persisted":False,"language_mode":"auto-detect"},"languages":languages}
    derived={"baseline_expected_language_matches":detected_baseline_matches,"baseline_expected_language_total":len(languages),"per_language":per_language,"all_baseline_encoder_repeats_exact":all(l["baseline_repeat"]["encoder_hash_equal"] for l in languages),"all_baseline_transcript_repeats_exact":all(l["baseline_repeat"]["transcript_equal"] for l in languages)}
    output_hash=sha256_json({"observations":observations,"derived_metrics":derived}); git_sha=os.environ.get("GITHUB_SHA"); run_id=os.environ.get("GITHUB_RUN_ID","local")
    bundle={"probe_id":"audio-multilingual-generalization-faster-whisper-tiny-v1","instrument":"audio-multilingual-feature-encoder-decoder-portability-suite","instrument_version":"mvp-1","model_identity":{"repository":UPSTREAM_REPO,"revision":UPSTREAM_REVISION,"logical_id":LOGICAL_ID,"model_class":"speech-to-text-asr-encoder-decoder"},"artifact_provenance":{"tracked":True,"foundry_repository":"SemperSupra/model-artifact-foundry","logical_artifact_id":LOGICAL_ID,"upstream_provider":"huggingface","upstream_repository":UPSTREAM_REPO,"upstream_revision":UPSTREAM_REVISION,"identity_kind":"oci","identity_digest":FOUNDRY_DIGEST,"foundry_record_ref":FOUNDRY_CATALOG_REF,"consumer_selection_ref":f"model-spelunker@{git_sha}" if git_sha else None,"verified":True,"verification_ref":"digest-pinned approved Foundry hydration with offline local reuse","tokenizer_artifact":None},"access_tier":"A2","evidence_level":"REPRODUCED","claim_tags":["AUDIO","MULTILINGUAL","GENERALIZATION","ENCODER_REPRESENTATION","DECODER_SURFACE"],"observations":observations,"derived_metrics":derived,"uncertainty":{"population":"nine repository-pinned functional samples; speaker provenance undocumented; not a speaker-demographics benchmark","reference":"perturbation robustness is relative to each sample's own baseline transcript, not a full ground-truth ASR accuracy benchmark","model_size":"Whisper tiny may underperform on some languages; failures are retained as evidence"},"known_assumptions":["repository MIT license is recorded as source-license evidence for the pinned sample repository","a single deterministic noise realization per utterance is sufficient for reconnaissance","Unicode character edit distance is more comparable than whitespace WER across mixed scripts"],"known_failure_modes":["sample voices may be synthetic or otherwise nonrepresentative","one utterance per language cannot estimate population robustness","baseline auto-language errors can confound perturbation language stability"],"cost":{"model_load_seconds":load_s,"experiment_seconds":science_s,"total_script_seconds":time.perf_counter()-started,"peak_rss_mib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.0},"provenance":{"run_id":str(run_id),"code_revision":git_sha,"model_revision":UPSTREAM_REVISION,"tokenizer_revision":UPSTREAM_REVISION,"environment":{"python":sys.version.split()[0],"platform":platform.platform(),"numpy":np.__version__,"faster_whisper":importlib.metadata.version("faster-whisper"),"ctranslate2":importlib.metadata.version("ctranslate2")},"randomness":{"numpy_rng_seed_per_utterance":0,"beam_size":1,"temperature":0.0},"raw_input_hash":sha256_json(resolved),"raw_output_hash":output_hash}}
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(bundle,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"languages":len(languages),"conditions_per_language":len(CONDITIONS),"baseline_language_matches":detected_baseline_matches,"all_repeats_exact":derived["all_baseline_encoder_repeats_exact"] and derived["all_baseline_transcript_repeats_exact"],"science_seconds":science_s,"peak_rss_mib":bundle["cost"]["peak_rss_mib"]},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
