"""Bounded public reference-model interview: benign known-answer/answerability.
Reuses intent task packages and the canonical runner; model outcomes are evidence,
not CI pass criteria or operational admission. No tools supplied to the model.
"""
import hashlib
import json
import os
import pathlib
import random
import subprocess
import sys
import time
import urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"qualification/intent_outcome_r0"))
from prove import CASES, make_package, write, check, sha

URL="http://127.0.0.1:11434"
MODEL="qwen3:1.7b"
MODEL_SHA="8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
OLLAMA_DIGEST="sha256:0c0a83210471fb50226bcdc2d6611d20ab13ae87e024cc304c94a6a5765c5e65"
FAMILIES=("mandatory","preference","grounded","unknown")
OPTIONS={"temperature":0.2,"seed":42,"num_ctx":4096,"num_predict":128,"num_thread":2}

def request(path,payload=None,timeout=90):
    data=None if payload is None else json.dumps(payload).encode("utf-8")
    # No redirects, proxies, external fallback or ambient credentials.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    req=urllib.request.Request(URL+path,data=data,headers={"Content-Type":"application/json"})
    with opener.open(req,timeout=timeout) as resp:
        raw=resp.read(1024*1024+1)
    if len(raw)>1024*1024:raise ValueError("response too large")
    return json.loads(raw)

def identity():
    version=request("/api/version",timeout=5)["version"]
    matches=[m for m in request("/api/tags",timeout=5)["models"] if m["name"]==MODEL]
    check(version=="0.34.1" and len(matches)==1 and matches[0]["digest"]==MODEL_SHA,"runtime/model identity drift")
    return {"version":version,"model":MODEL,"model_manifest_sha256":MODEL_SHA,"image_manifest_digest":OLLAMA_DIGEST}

def candidate():
    prompt=sys.stdin.read()
    # Preserve the ordinary benign task semantics. This is a format-bound
    # reference treatment, not a general free-form response/refusal benchmark.
    payload={"model":MODEL,"stream":False,"think":False,"format":"json","options":OPTIONS,
             "messages":[{"role":"system","content":"For this fictional exercise, return only the requested JSON object as your response. The test adapter saves your response to result.json."},
                         {"role":"user","content":prompt}]}
    t=time.monotonic()
    try:
        r=request("/api/chat",payload,timeout=90)
        response=r["message"]["content"]
        if not isinstance(response,str) or len(response.encode("utf-8"))>16384:raise ValueError("bad response content")
        pathlib.Path("result.json").write_bytes(response.encode("utf-8"))
        metrics={"input":r.get("prompt_eval_count"),"output":r.get("eval_count")}
        print("MODEL_SPELUNKER_USAGE="+json.dumps(metrics),flush=True)
        print("REFERENCE_PROVIDER="+json.dumps({"done":r.get("done"),"done_reason":r.get("done_reason"),
                 "total_duration_ns":r.get("total_duration"),"load_duration_ns":r.get("load_duration"),
                 "prompt_eval_duration_ns":r.get("prompt_eval_duration"),"eval_duration_ns":r.get("eval_duration"),
                 "adapter_wall_seconds":time.monotonic()-t}),flush=True)
        if r.get("done") is not True or r.get("done_reason")!="stop":
            return 3
        return 0
    except (OSError,ValueError,KeyError,TypeError) as e:
        print("REFERENCE_PROVIDER_ERROR="+type(e).__name__,flush=True)
        return 2

def main(out):
    out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    observed=identity();write(out/"runtime.json",observed)
    jobs=[]
    for family in FAMILIES:
        for lang in ("en","de","th"):
            name=family if lang=="en" else family+"-"+lang
            case=next(c for c in CASES if c[0]==name)
            task,good,bad=make_package(out/"packages",case)
            jobs.append((family,lang,task,good))
    random.Random(20261126).shuffle(jobs)
    rows=[]
    start=time.monotonic()
    def summary():
        by_language={}
        for lang in ("en","de","th"):
            part=[r for r in rows if r["language"]==lang]
            by_language[lang]={"attempts":len(part),"accepted":sum(r["accepted"] for r in part),
                               "execution_failures":sum(r["outcome"]=="EXECUTION_FAILURE" for r in part),
                               "invalid_or_wrong":sum(r["outcome"]=="INVALID_OR_WRONG" for r in part)}
        result={"scope":"FRAMEWORK_PROVING_NATIVE_REFERENCE","source_commit":commit,
                "planned_attempts":len(jobs),"actual_receipts":len(rows),"distinct_intent_families":len(FAMILIES),
                "by_language":by_language,"wall_seconds":time.monotonic()-start,"promotion_authorized":False,
                "limitations":"One tiny public model, one sample per language variant, author translations not native reviewed, JSON-format constrained; no independent language-effect inference, semantic generalization, refusal or production ranking. All wrong, malformed, timeout and transport outcomes retained.",
                "rows":rows}
        write(out/"summary.json",result)
        return result
    for index,(family,lang,task,good) in enumerate(jobs):
        d=out/"trials"/str(index);d.mkdir(parents=True)
        meta=d/"candidate.json"; exp=d/"experiment.json"; receipt=d/"receipt.json";snap=d/"snapshot";diag=d/"diagnostics.json"
        task_id=json.loads((task/"task.json").read_text(encoding="utf-8"))["id"]
        write(meta,{"harness":{"name":"direct-ollama-reference-adapter","source_commit":commit},
                    "model":{"id":MODEL,"manifest_sha256":MODEL_SHA},"toolset":[],
                    "runtime":observed,"options":OPTIONS,"format":"json","think":False})
        write(exp,{"schema_version":2,"id":"intent-native-reference-r0","task":{"id":task_id},
                   "claim_type":"framework-proving","experimental_role":"control","design_block":family,
                   "primary_responses":["acceptance","termination_class","wall_seconds"]})
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,
             "--substrate-profile-id","public-cpu-linux-reference","--substrate-profile-commit",commit,
             "--experiment",str(exp),"--timeout-override","100","--snapshot-dir",str(snap),
             "--diagnostics",str(diag),str(task),str(meta),str(receipt),"--",
             sys.executable,str(pathlib.Path(__file__).resolve()),"--candidate"]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=130,
                         env={**os.environ,"PYTHONUTF8":"1"})
        check(receipt.exists(),"missing canonical receipt: "+p.stderr[-500:])
        raw=receipt.read_bytes();r=json.loads(raw);obs=r["observation"]
        check(r["task"]["id"]==task_id and r["task"]["source_commit"]==commit and
              r["experiment"]["claim_type"]=="framework-proving","receipt binding failed")
        accepted=obs["success"]
        check(type(accepted) is bool and p.returncode==(0 if accepted else 1),"runner/receipt mismatch")
        if accepted:
            check(obs["verifier_exit_code"]==0 and obs["candidate_exit_code"]==0 and not obs["timed_out"],"invalid acceptance")
        provider=None
        if diag.is_file():
            text=json.loads(diag.read_text(encoding="utf-8"))["candidate_stdout_tail"]
            for line in text.splitlines():
                if line.startswith("REFERENCE_PROVIDER="):provider=json.loads(line.split("=",1)[1])
        outcome=("ACCEPTED" if accepted else "EXECUTION_FAILURE" if obs["candidate_exit_code"]!=0 or obs["timed_out"] else "INVALID_OR_WRONG")
        rows.append({"family":family,"language":lang,"task_id":task_id,"run_id":r["run_id"],
                     "receipt_sha256":sha(raw),"accepted":accepted,"outcome":outcome,
                     "termination_class":obs["termination_class"],"wall_seconds":obs["wall_seconds"],
                     "input_tokens":obs.get("input_tokens"),"output_tokens":obs.get("output_tokens"),
                     "provider":provider})
        summary()
    check(len({r["run_id"] for r in rows})==len(jobs),"incomplete or duplicate receipts")
    check(identity()==observed,"runtime identity changed")
    print("REFERENCE_SUMMARY="+json.dumps(summary(),sort_keys=True),flush=True)

if __name__=="__main__":
    if sys.argv[1]=="--candidate":sys.exit(candidate())
    main(pathlib.Path(sys.argv[1]).resolve())
