"""Bounded offline ASR evaluator calibration, not TTS or operational qualification.
LibriSpeech: Panayotov, Chen, Povey, Khudanpur, ICASSP 2015, OpenSLR SLR12,
CC BY 4.0 (https://www.openslr.org/12/); repacked dev-clean subset:
https://huggingface.co/datasets/hf-internal-testing/librispeech_asr_dummy .
Aligned corpus text is the reference; no fresh human review claimed.
"""
import hashlib,json,pathlib,random,re,subprocess,sys,tempfile,time,wave
from speech_calibration import observe as sphinx_observe,edit_distance,words
ROOT=pathlib.Path(__file__).resolve().parents[2]
DATA_SHA="4e69a06fa5edc90921e5e7e39a7084881f8b3ed9c805c574f4f39c6fde27c603"
MODEL_SHA="1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a"
MODEL_REV="2919638eccc5115566830024836f1ce314e8b72a"
ARMS=("pocketsphinx","whisper")
ATTRIBUTION="LibriSpeech ASR corpus by V. Panayotov, G. Chen, D. Povey and S. Khudanpur, OpenSLR SLR12, CC BY 4.0; subset repacked as hf-internal-testing/librispeech_asr_dummy. Decoded to mono PCM."
def sha(b):return "sha256:"+hashlib.sha256(b).hexdigest()
def write(p,x):p.write_text(json.dumps(x,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def check(ok,msg):
    if not ok:raise RuntimeError(msg)
def norm(s):return words(s.replace("’","'"))
def strict(raw):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError("duplicate")
            d[k]=v
        return d
    x=json.loads(raw,object_pairs_hook=pairs)
    if type(x) is not dict or set(x)!={"transcript"} or type(x["transcript"]) is not str:raise ValueError("shape")
    return x["transcript"]
def prepare(data,out):
    import pyarrow.parquet as pq
    check(sha(data.read_bytes())=="sha256:"+DATA_SHA,"dataset drift")
    table=pq.read_table(data,columns=["id","audio","text","speaker_id","chapter_id"])
    check(table.num_rows==73,"unexpected corpus shape")
    source=sorted(table.to_pylist(),key=lambda r:r["id"]);random.Random(20261126).shuffle(source)
    selected=[];working=out/"prepared";working.mkdir()
    for r in source:
        if not re.fullmatch(r"[0-9]+-[0-9]+-[0-9]+",r["id"]) or not 4<=len(norm(r["text"]))<=32:continue
        raw=r["audio"]["bytes"]
        if type(raw) is not bytes or not 0<len(raw)<=2*1024*1024:continue
        p=working/(r["id"]+".wav")
        with tempfile.TemporaryDirectory() as temp:
            x=pathlib.Path(temp)/"clip.flac";x.write_bytes(raw)
            subprocess.run(["ffmpeg","-nostdin","-v","error","-y","-i",str(x),"-ar","16000","-ac","1","-c:a","pcm_s16le",str(p)],check=True,timeout=30)
        with wave.open(str(p),"rb") as f:
            check((f.getnchannels(),f.getsampwidth(),f.getframerate())==(1,2,16000),"bad PCM")
            sec=f.getnframes()/16000
        if not 1<=sec<=12:p.unlink();continue
        selected.append({"id":r["id"],"text":r["text"],"speaker_id":r["speaker_id"],"chapter_id":r["chapter_id"],
                         "source_audio_sha256":sha(raw),"wav_sha256":sha(p.read_bytes()),"duration_seconds":sec})
        if len(selected)==6:break
    check(len(selected)==6,"not enough eligible samples")
    p=working/"silence.wav"
    with wave.open(str(p),"wb") as f:
        f.setparams((1,2,16000,16000,"NONE","not compressed"));f.writeframes(b"\0"*32000)
    selected.append({"id":"silence","text":"","speaker_id":None,"chapter_id":None,"source_audio_sha256":None,
                     "wav_sha256":sha(p.read_bytes()),"duration_seconds":1.0})
    write(out/"corpus-selection.json",{"attribution":ATTRIBUTION,"dataset_sha256":DATA_SHA,"selected":selected})
    return selected
VERIFIER=r'''
import hashlib,json,pathlib,re,sys
p=pathlib.Path(sys.argv[1])
def pairs(items):
    d={}
    for k,v in items:
        if k in d:raise ValueError("duplicate")
        d[k]=v
    return d
try:
    ok={x.name for x in p.iterdir()}=={"speech.wav","result.json"} and all(x.is_file() and not x.is_symlink() for x in p.iterdir())
    x=json.loads((p/"result.json").read_text(encoding="utf-8"),object_pairs_hook=pairs)
    actual=re.findall(r"[a-z]+(?:'[a-z]+)?",x["transcript"].replace("’","'").lower())
    ok=ok and set(x)=={"transcript"} and actual==EXPECTED and hashlib.sha256((p/"speech.wav").read_bytes()).hexdigest()==EXPECTED_SHA
except (OSError,ValueError,TypeError,AttributeError,KeyError):ok=False
sys.exit(0 if ok else 1)
'''
def package(out,case):
    task=out/"packages"/case["id"];fixture=task/"fixture";fixture.mkdir(parents=True)
    import shutil
    shutil.copyfile(out/"prepared"/(case["id"]+".wav"),fixture/"speech.wav")
    code=VERIFIER.replace("EXPECTED_SHA",repr(case["wav_sha256"].split(":")[1])).replace("EXPECTED",repr(norm(case["text"])))
    (task/"verify.py").write_text(code,encoding="utf-8")
    write(task/"task.json",{"schema_version":1,"id":"asr-corpus-"+case["id"]+"-v0","task_class":"framework.asr-calibration",
        "instruction":"Transcribe speech.wav literally as JSON with exactly one string field transcript. Use an empty string for silence. Do not alter the audio.",
        "fixture":"fixture","verifier":"verify.py","limits":{"wall_seconds":100},"success":{"kind":"deterministic-final-state"},
        "allowed_write_paths":["result.json"],"projected_tools":["read_file","write_file"]})
    return task
def candidate(arm,model_dir):
    try:
        if arm=="pocketsphinx":
            d=sphinx_observe(pathlib.Path("speech.wav"),"")
            if d["status"] in ("EVALUATOR_ERROR","ARTIFACT_INVALID") or d["transcript"] is None:raise ValueError("ASR failed")
            transcript=d["transcript"]
        elif arm=="whisper":
            from faster_whisper import WhisperModel
            model=WhisperModel(str(model_dir),device="cpu",compute_type="int8",cpu_threads=2,num_workers=1,local_files_only=True)
            segs,_=model.transcribe("speech.wav",language="en",beam_size=1,temperature=0,condition_on_previous_text=False,vad_filter=False)
            transcript=" ".join(s.text.strip() for s in segs).strip()
        else:raise ValueError("unknown arm")
        write(pathlib.Path("result.json"),{"transcript":transcript});return 0
    except Exception as e:
        print("ASR_ERROR="+type(e).__name__,flush=True);return 2
def main(data,model,out):
    out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    check(sha((model/"model.bin").read_bytes())=="sha256:"+MODEL_SHA,"model weight drift")
    model_files=[{"path":p.relative_to(model).as_posix(),"sha256":sha(p.read_bytes())} for p in sorted(model.rglob("*")) if p.is_file()]
    check(all((model/n).is_file() for n in ("model.bin","config.json","tokenizer.json","vocabulary.txt")),"model closure incomplete")
    runtime={"whisper_source_revision":MODEL_REV,"whisper_files":model_files,"dataset_sha256":DATA_SHA,
             "package_freeze":subprocess.check_output([sys.executable,"-m","pip","freeze"],text=True).splitlines()}
    write(out/"runtime.json",runtime);cases=prepare(data,out)
    jobs=[]
    for i,case in enumerate(cases):
        task=package(out,case)
        for arm in (ARMS if i%2==0 else tuple(reversed(ARMS))):jobs.append((case,task,arm))
    rows=[];start=time.monotonic()
    for i,(case,task,arm) in enumerate(jobs):
        d=out/"trials"/str(i);d.mkdir(parents=True)
        meta=d/"candidate.json";exp=d/"experiment.json";receipt=d/"receipt.json";snap=d/"snapshot"
        task_id=json.loads((task/"task.json").read_text())["id"]
        write(meta,{"harness":{"name":"offline-asr-reference","source_commit":commit},"model":{"id":arm},"toolset":["read_file","write_file"],"runtime":runtime})
        write(exp,{"schema_version":2,"id":"human-speech-asr-reference-r1","task":{"id":task_id},"claim_type":"framework-proving","experimental_role":"control","design_block":case["id"],"primary_responses":["acceptance","word_error_rate"]})
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,"--substrate-profile-id","public-linux-asr-reference","--substrate-profile-commit",commit,
             "--experiment",str(exp),"--snapshot-dir",str(snap),str(task),str(meta),str(receipt),"--",sys.executable,str(pathlib.Path(__file__).resolve()),"--candidate",arm,str(model)]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=130)
        check(receipt.is_file(),"missing receipt "+p.stderr[-400:])
        raw=receipt.read_bytes();r=json.loads(raw);obs=r["observation"]
        check(r["task"]["id"]==task_id and r["task"]["source_commit"]==commit and r["experiment"]["claim_type"]=="framework-proving","receipt binding")
        artifact=snap/"result.json";m=json.loads((snap/"snapshot_manifest.json").read_text())["files"]["result.json"]
        check(m["present"]==artifact.is_file(),"snapshot presence")
        transcript=None
        if artifact.is_file():
            check(m["sha256"]==sha(artifact.read_bytes()),"snapshot digest")
            try:transcript=strict(artifact.read_bytes())
            except (ValueError,TypeError):pass
        done=obs["candidate_exit_code"]==0 and not obs["timed_out"]
        expected=norm(case["text"]);actual=norm(transcript) if transcript is not None else None
        edits=edit_distance(expected,actual) if actual is not None and done else None
        check(obs["success"] is (done and actual==expected) and p.returncode==(0 if obs["success"] else 1),"independent transcript check mismatch")
        rows.append({"clip_id":case["id"],"arm":arm,"duration_seconds":case["duration_seconds"],"reference_words":len(expected),
            "edits":edits,"wer":edits/len(expected) if edits is not None and expected else None,
            "completed":done,"accepted":obs["success"],"transcript":transcript,"reference":case["text"],
            "wall_seconds":obs["wall_seconds"],"run_id":r["run_id"],"receipt_sha256":sha(raw),"artifact_sha256":m.get("sha256")})
        write(out/"partial-rows.json",rows)
    check(len({r["run_id"] for r in rows})==len(jobs),"incomplete")
    groups={}
    for arm in ARMS:
        part=[r for r in rows if r["arm"]==arm];speech=[r for r in part if r["reference_words"]]
        complete=[r for r in speech if r["edits"] is not None];silence=next(r for r in part if not r["reference_words"])
        groups[arm]={"speech_attempts":len(speech),"speech_exact":sum(r["accepted"] for r in speech),
            "execution_failures":sum(not r["completed"] for r in part),"observed_speech_pairs":len(complete),
            "corpus_wer":sum(r["edits"] for r in complete)/sum(r["reference_words"] for r in complete) if len(complete)==len(speech) else None,
            "silence_empty":silence["accepted"],"all_attempt_wall_seconds":sum(r["wall_seconds"] for r in part)}
    summary={"scope":"FRAMEWORK_PROVING_ONLY","source_commit":commit,"actual_receipts":len(rows),"speech_clips":6,"silence_controls":1,
        "speakers":len({r["speaker_id"] for r in cases if r["speaker_id"] is not None}),"groups":groups,"elapsed_seconds":time.monotonic()-start,
        "attribution":ATTRIBUTION,"promotion_authorized":False,"limitations":"Public aligned book text, no fresh human audit, tiny fixed English sample, potential training overlap. WER normalization limited to English words. Includes per-attempt model loading; no broad accuracy, TTS or operational qualification.","rows":rows}
    write(out/"summary.json",summary);print("HUMAN_ASR="+json.dumps({k:v for k,v in summary.items() if k!="rows"}),flush=True)
if __name__=="__main__":
    if sys.argv[1]=="--candidate":sys.exit(candidate(sys.argv[2],pathlib.Path(sys.argv[3])))
    main(*(pathlib.Path(x).resolve() for x in sys.argv[1:]))
