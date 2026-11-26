"""Speech-fidelity measurement calibration using public deterministic TTS and ASR.

No neural generative model or human-transcription claim. Authored synthesis inputs
are known; the actual recognizer can disagree. Preserve disagreement, don't
require a perfect recognizer to pass the experimental mechanism.
"""
import hashlib
import json
import os
import pathlib
import random
import re
import subprocess
import sys
import tempfile
import time
import wave
from pocketsphinx import Decoder, get_model_path

ROOT=pathlib.Path(__file__).resolve().parents[2]
CASES=[
 ("door","the red door is open",{"good":"the red door is open","omission":"the door is open","substitution":"the blue door is open","reorder":"the open door is red"}),
 ("direction","turn left then turn right",{"good":"turn left then turn right","omission":"turn left then right","substitution":"turn left then turn left","reorder":"turn right then turn left"}),
 ("count","one two three four",{"good":"one two three four","omission":"one two four","substitution":"one two five four","reorder":"one three two four","silence":None}),
]
def write(p,x):p.write_text(json.dumps(x,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def sha(b):return "sha256:"+hashlib.sha256(b).hexdigest()
def check(ok,msg):
    if not ok:raise RuntimeError(msg)
def words(s):return re.findall(r"[a-z]+(?:'[a-z]+)?",s.lower())
def edit_distance(a,b):
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        nxt=[i]
        for j,y in enumerate(b,1):
            nxt.append(min(nxt[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=nxt
    return row[-1]
def wer(a,b):
    aa,bb=words(a),words(b)
    return edit_distance(aa,bb)/len(aa) if aa else None
def generate(family,arm):
    case=next(c for c in CASES if c[0]==family)
    utterance=case[2][arm]
    if utterance is None:
        with wave.open("speech.wav","wb") as f:
            f.setparams((1,2,16000,16000,"NONE","not compressed"));f.writeframes(b"\0"*32000)
        return
    with tempfile.TemporaryDirectory() as tmp:
        source=pathlib.Path(tmp)/"source.wav"
        subprocess.run(["espeak-ng","-v","en-us","-s","145","-w",str(source),utterance],check=True,timeout=20)
        subprocess.run(["ffmpeg","-nostdin","-v","error","-y","-i",str(source),"-ar","16000","-ac","1","-c:a","pcm_s16le","speech.wav"],check=True,timeout=20)
def observe(clip,expected):
    if not clip.is_file() or clip.is_symlink() or clip.stat().st_size>1024*1024:
        return {"accepted":False,"status":"ARTIFACT_INVALID","transcript":None,"intent_wer":None}
    try:
        with wave.open(str(clip),"rb") as f:
            if (f.getnchannels(),f.getsampwidth(),f.getframerate(),f.getcomptype())!=(1,2,16000,"NONE"):
                return {"accepted":False,"status":"ARTIFACT_INVALID","transcript":None,"intent_wer":None}
            n=f.getnframes();data=f.readframes(n)
        if not 1<=n<=160000 or len(data)!=n*2:
            return {"accepted":False,"status":"ARTIFACT_INVALID","transcript":None,"intent_wer":None}
        if not any(data):
            return {"accepted":False,"status":"NO_SIGNAL","transcript":"","intent_wer":1.0,"duration_seconds":n/16000}
        model=pathlib.Path(get_model_path())
        config=Decoder.default_config()
        for key,path in (("-hmm",model/"en-us"),("-lm",model/"en-us.lm.bin"),("-dict",model/"cmudict-en-us.dict")):
            check(path.exists(),"missing ASR component")
            config.set_string(key,str(path))
        config.set_float("-samprate",16000.0)
        config.set_string("-logfn",os.devnull)
        decoder=Decoder(config);decoder.start_utt();decoder.process_raw(data,False,True);decoder.end_utt()
        hyp=decoder.hyp();transcript=hyp.hypstr if hyp is not None else ""
        return {"accepted":words(transcript)==words(expected),"status":"RECOGNIZED" if transcript else "NO_HYPOTHESIS",
                "transcript":transcript,"intent_wer":wer(expected,transcript),"duration_seconds":n/16000}
    except (OSError,ValueError,RuntimeError,wave.Error,EOFError) as exc:
        return {"accepted":False,"status":"EVALUATOR_ERROR","error_type":type(exc).__name__,"transcript":None,"intent_wer":None}
def verify(root,expected,fixture_sha):
    try:
        if {p.name for p in root.iterdir()}!={"intent.json","speech.wav"}:return 1
        f=root/"intent.json"
        if f.is_symlink() or not f.is_file() or sha(f.read_bytes())!=fixture_sha:return 1
        detail=observe(root/"speech.wav",expected)
        print(json.dumps(detail,sort_keys=True),flush=True)
        return 2 if detail["status"]=="EVALUATOR_ERROR" else 0 if detail["accepted"] else 1
    except OSError:return 2
def main(out):
    out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    runtime={"packages":subprocess.check_output(["dpkg-query","-W","-f=${Package}=${Version}\\n","espeak-ng","python3-pocketsphinx","pocketsphinx-en-us","ffmpeg"],text=True).splitlines(),
             "python":sys.version.split()[0]}
    # Verify word edit-distance accounting independently of actual ASR.
    controls=[("one two","one two",0),("one two","one",.5),("one two","one three",.5),("one two","one two three",.5),("one two","two one",1),("one two","",1)]
    for a,b,w in controls:check(wer(a,b)==w,"WER control mismatch")
    check(wer("","one") is None,"empty-reference denominator")
    model=pathlib.Path(get_model_path())
    check(model.is_dir(),"ASR model root missing")
    model_files=[{"path":p.relative_to(model).as_posix(),"sha256":sha(p.read_bytes())} for p in sorted(model.rglob("*")) if p.is_file()]
    check(bool(model_files),"no ASR model files")
    write(out/"runtime.json",{"runtime":runtime,"asr_model_files":model_files})
    jobs=[]
    for family,expected,arms in CASES:
        task=out/"packages"/family;(task/"fixture").mkdir(parents=True)
        write(task/"fixture/intent.json",{"requested_transcript":expected})
        fixture_sha=sha((task/"fixture/intent.json").read_bytes())
        (task/"verify.py").write_text("import subprocess,sys\nraise SystemExit(subprocess.call([sys.executable,"+repr(str(pathlib.Path(__file__).resolve()))+",'--verify',sys.argv[1],"+repr(expected)+","+repr(fixture_sha)+"]))\n",encoding="utf-8")
        task_id="speech-fidelity-"+family+"-v0"
        write(task/"task.json",{"schema_version":1,"id":task_id,"task_class":"framework.speech-fidelity",
             "instruction":"Synthesize verbatim the public fixture sentence into a 16 kHz mono PCM WAV file speech.wav.",
             "fixture":"fixture","verifier":"verify.py","limits":{"wall_seconds":25},
             "success":{"kind":"deterministic-final-state"},"allowed_write_paths":["speech.wav"],"projected_tools":["write_file"]})
        jobs.extend((family,expected,arm,spoken,task) for arm,spoken in arms.items())
    random.Random(20261126).shuffle(jobs);rows=[];start=time.monotonic()
    for i,(family,expected,arm,spoken,task) in enumerate(jobs):
        d=out/"trials"/str(i);d.mkdir(parents=True)
        meta=d/"candidate.json";exp=d/"experiment.json";receipt=d/"receipt.json";snap=d/"snapshot";diag=d/"diagnostics.json"
        task_id="speech-fidelity-"+family+"-v0"
        write(meta,{"harness":{"name":"scripted-espeak-control"},"model":{"id":"espeak-ng deterministic reference"},"toolset":["write_file"],"arm":arm,"runtime":runtime})
        write(exp,{"schema_version":2,"id":"speech-evaluator-controls-r0","task":{"id":task_id},"claim_type":"framework-proving",
                   "experimental_role":"control","design_block":family,"primary_responses":["acceptance","speech_fidelity"]})
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,"--substrate-profile-id","public-linux-speech-reference",
             "--substrate-profile-commit",commit,"--experiment",str(exp),"--snapshot-dir",str(snap),"--diagnostics",str(diag),
             str(task),str(meta),str(receipt),"--",sys.executable,str(pathlib.Path(__file__).resolve()),"--candidate",family,arm]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=90)
        check(receipt.exists(),"canonical receipt absent")
        raw=receipt.read_bytes();r=json.loads(raw);obs=r["observation"]
        check(r["task"]["id"]==task_id and r["task"]["source_commit"]==commit and r["experiment"]["claim_type"]=="framework-proving","receipt identity")
        check(obs["candidate_exit_code"]==0 and not obs["timed_out"],"synthesis execution failed")
        clip=snap/"speech.wav";m=json.loads((snap/"snapshot_manifest.json").read_text())["files"]["speech.wav"]
        check(m["present"] and m["sha256"]==sha(clip.read_bytes()),"snapshot integrity")
        # Re-decode captured speech, independent of candidate metadata.
        detail=observe(clip,expected)
        check(detail["status"]!="EVALUATOR_ERROR","ASR evaluator failure: "+str(detail))
        check(obs["success"] is detail["accepted"] and p.returncode==(0 if detail["accepted"] else 1),"snapshot adjudication mismatch")
        transcript=detail["transcript"]
        rows.append({"family":family,"arm":arm,"requested":expected,"authored_synthesis_input":spoken,"accepted":obs["success"],
                     "synthesis_input_matches_intent":spoken==expected,"asr":detail,
                     "asr_wer_against_synthesis_input":wer(spoken,transcript) if spoken is not None and transcript is not None else None,
                     "run_id":r["run_id"],"receipt_sha256":sha(raw),"artifact_sha256":m["sha256"]})
    check(len({r["run_id"] for r in rows})==len(jobs),"duplicate or missing receipts")
    good=[r for r in rows if r["synthesis_input_matches_intent"]];bad=[r for r in rows if not r["synthesis_input_matches_intent"]]
    s={"scope":"FRAMEWORK_PROVING_ONLY","source_commit":commit,"actual_receipts":len(rows),"wer_controls":len(controls)+1,
       "matching_synthesis_inputs":len(good),"accepted_matching_inputs":sum(r["accepted"] for r in good),
       "mutated_synthesis_inputs":len(bad),"accepted_mutated_inputs":sum(r["accepted"] for r in bad),
       "asr_mismatch_on_matching_input":sum(r["asr"]["intent_wer"]!=0 for r in good),
       "elapsed_seconds":time.monotonic()-start,"runtime":runtime,"promotion_authorized":False,
       "limitations":"English deterministic espeak-ng synthesis, offline PocketSphinx; source script is not independently human-verified actual speech. Recognizer errors cannot establish generator omissions/refusals. No natural voice, neural TTS, multilingual, speaker identity or production evaluator qualification. WER counts tokenized English words only; silence has no source WER.","rows":rows}
    write(out/"summary.json",s);print("SPEECH_R0="+json.dumps(s,sort_keys=True),flush=True)
if __name__=="__main__":
    if sys.argv[1]=="--candidate":generate(sys.argv[2],sys.argv[3])
    elif sys.argv[1]=="--verify":sys.exit(verify(pathlib.Path(sys.argv[2]),sys.argv[3],sys.argv[4]))
    else:main(pathlib.Path(sys.argv[1]).resolve())
