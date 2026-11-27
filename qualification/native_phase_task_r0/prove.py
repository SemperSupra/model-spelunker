"""Native request-to-task binding; public synthetic only, trusted probe, not untrusted attestation."""
import copy,hashlib,json,math,os,pathlib,subprocess,sys,uuid
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"qualification/serving_fanout_r0/streaming"))
import streaming_probe as sp
PIN="8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
def digest(b):return "sha256:"+hashlib.sha256(b).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(",",":")).encode()
def write(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def candidate(packetpath,sidecar):
    packet=json.loads(packetpath.read_bytes())
    client=sp.opener();base=sp.origin("http://127.0.0.1:11434")
    exact=sp.digest(client,base,sp.MODEL,PIN)
    assert exact==PIN
    text=[]
    instruction=sys.stdin.read()
    if instruction.strip()!="Replace the entire contents of value.txt with READY followed by a newline.":raise ValueError("unexpected synthetic task")
    prompt=instruction+" Reply only with the desired file contents, no explanation."
    metrics=sp.stream_one(client,base,sp.MODEL,0,0,"shared",prompt_text=prompt,response_sink=text.append,strict_phases=True)
    # Only a bounded synthetic result, not raw traces or private text.
    result=("READY\n" if "".join(text).strip()=="READY" else "WRONG\n").encode()
    pathlib.Path("value.txt").write_bytes(result)
    write(sidecar,{"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","launch_id":packet["launch_id"],"packet_digest":digest(canonical(packet)),"request_id":packet["request_id"],"model_digest":exact,"tokenizer_identity":"bound to exact Ollama model manifest; separate tokenizer digest UNKNOWN","timing_source":"Ollama native prompt_eval_count/eval_count and durations; client monotonic first nonempty response","cache_reused_tokens":None,"reasoning_tokens":None,"output_sha256":digest(result),"metrics":metrics})
def bind(packet,receipt_raw,sidecar,output):
    r=json.loads(receipt_raw)
    if r.get("schema_version")!=2 or r.get("experiment",{}).get("claim_type")!="framework-proving" or sidecar["scope"]!="FRAMEWORK_PROVING_ONLY":raise ValueError("purpose")
    if r["launch"]!={"launch_id":packet["launch_id"],"packet_digest":digest(canonical(packet))}:raise ValueError("launch binding")
    if sidecar["launch_id"]!=packet["launch_id"] or sidecar["packet_digest"]!=digest(canonical(packet)) or sidecar["request_id"]!=packet["request_id"]:raise ValueError("request binding")
    if sidecar["model_digest"]!=PIN or r["candidate"]["model"]["digest"]!=PIN or packet["model_digest"]!=PIN:raise ValueError("model binding")
    if sidecar["output_sha256"]!=digest(output):raise ValueError("output binding")
    m=sidecar["metrics"]
    for k in ("prompt_tokens","output_tokens","prefill_ms","decode_ms","load_ms","ttft_ms","elapsed_ms"):
        v=m[k]
        if type(v) not in (int,float) or not math.isfinite(v) or v<0:raise ValueError("invalid metric")
    if m["ttft_ms"]<=0 or m["elapsed_ms"]<m["ttft_ms"] or m["elapsed_ms"]>r["observation"]["wall_seconds"]*1000+100:raise ValueError("timing chronology")
    if any(type(m[k]) is not int or m[k]<=0 for k in ("prompt_tokens","output_tokens")):raise ValueError("invalid native counts")
    return {"scope":"FRAMEWORK_PROVING_ONLY","run_id":r["run_id"],"receipt_sha256":digest(receipt_raw),"request_id":sidecar["request_id"],"model_digest":PIN,"accepted":r["observation"]["success"],"metrics":m,"prefill_tps":1000*m["prompt_tokens"]/m["prefill_ms"] if m["prefill_ms"]>0 else None,"decode_tps":1000*m["output_tokens"]/m["decode_ms"] if m["decode_ms"]>0 else None,"cached_tokens":None,"reasoning_tokens":None,"timing_source":sidecar["timing_source"],"tokenizer_identity":sidecar["tokenizer_identity"],"source_scope":"trusted public probe; not independent server attestation"}
def proof(out):
    out.mkdir();rows=[]
    commit=os.environ["GITHUB_SHA"]
    for rep in range(3):
        d=out/str(rep);d.mkdir()
        packet={"launch_id":"native-"+uuid.uuid4().hex,"request_id":"req-"+uuid.uuid4().hex,"model_digest":PIN}
        pp=d/"packet.json";write(pp,packet)
        meta=d/"candidate.json";write(meta,{"harness":{"name":"native-stream-probe"},"model":{"id":sp.MODEL,"digest":PIN},"toolset":["write_file"]})
        exp=d/"experiment.json";write(exp,{"schema_version":2,"id":"native-phase-task-r0","task":{"id":"text-repair-v0"},"claim_type":"framework-proving","experimental_role":"control","design_block":rep,"primary_responses":["accepted","native_phase"]})
        receipt=d/"receipt.json";side=d/"phase.json";snap=d/"snapshot"
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,"--substrate-profile-id","framework-public-linux","--substrate-profile-commit",commit,"--experiment",str(exp),"--launch-id",packet["launch_id"],"--launch-packet-digest",digest(canonical(packet)),"--snapshot-dir",str(snap),str(ROOT/"qualification/tasks/text-repair-v0"),str(meta),str(receipt),"--",sys.executable,__file__,"candidate",str(pp),str(side)]
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=150)
        assert receipt.exists() and side.exists(),p.stderr
        raw=receipt.read_bytes();phase=json.loads(side.read_bytes());output=(snap/"value.txt").read_bytes()
        result=bind(packet,raw,phase,output);write(d/"joined.json",result);rows.append(result)
        if rep==0:
            for k,val in [("request_id","orphan"),("packet_digest","wrong"),("model_digest","wrong"),("output_sha256","wrong")]:
                bad=copy.deepcopy(phase);bad[k]=val
                try:bind(packet,raw,bad,output)
                except ValueError:pass
                else:raise AssertionError(k)
            bad=copy.deepcopy(phase);bad["metrics"]["prefill_ms"]=float("nan")
            try:bind(packet,raw,bad,output)
            except ValueError:pass
            else:raise AssertionError("nonfinite")
    assert len({r["run_id"] for r in rows})==3 and len({r["request_id"] for r in rows})==3
    summary={"scope":"FRAMEWORK_PROVING_ONLY","actual_native_requests":3,"bound_receipts":3,"accepted":sum(r["accepted"] for r in rows),"negative_controls":5,"rows":rows,"limitations":"single trusted probe, no autonomous agent qualification; not independent server attestation; no GPU energy or cached-token counts"}
    write(out/"summary.json",summary);print("NATIVE_TASK_JOIN="+json.dumps(summary),flush=True)
if __name__=="__main__":
    if sys.argv[1]=="candidate":candidate(pathlib.Path(sys.argv[2]),pathlib.Path(sys.argv[3]))
    else:proof(pathlib.Path(sys.argv[2]).resolve())
