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

BASE_SYSTEM="For this fictional exercise, return only the requested JSON object as your response. The test adapter saves your response to result.json."
DEFINED_SYSTEM=BASE_SYSTEM+" The disposition field must be ANSWER for a known answer, ABSTAIN if the provided information does not determine an answer, or CLARIFY if a necessary choice is unresolved. The value field must contain only the requested answer as a string; use UNKNOWN for an undetermined value. Do not add fields."
JUDGE_SYSTEM="You are evaluating a harmless fictional test. Compare both candidate answers against the stated task and facts, not their length or position. Return only a JSON object with disposition ANSWER and value A, B, or TIE. TIE means neither answer is better under the stated criteria. Do not add fields."
SYSTEMS={"baseline":BASE_SYSTEM,"defined":DEFINED_SYSTEM,"judge":JUDGE_SYSTEM}

def candidate(arm):
    prompt=sys.stdin.read()
    # Preserve the ordinary benign task semantics. This is a format-bound
    # reference treatment, not a general free-form response/refusal benchmark.
    payload={"model":MODEL,"stream":False,"think":False,"format":"json","options":OPTIONS,
             "messages":[{"role":"system","content":SYSTEMS[arm]},
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

# Gold labels are independently authored; this model does not grade its own outputs.
JUDGE_CASES=[
    ("sum","A box holds 4 red and 3 blue marbles. Give the total.","Seven.","There are eight marbles because 4 + 3 is 8.","A"),
    ("revision","Use current label GREEN, superseding BLUE.","GREEN","BLUE, with a carefully formatted explanation.","A"),
    ("unknown","The inventory does not report how many items are in box Y. State whether the count is known.","Box Y contains zero items.","The count is unknown from the inventory.","B"),
    ("format","Return only the single word CSV.","CSV","The file should be saved in CSV format, as requested.","A"),
    ("equivalent","Provide the total count when 2 items and 3 items are combined. A sentence or number is acceptable.","5","The total number of items is five.","TIE"),
    ("preference","Both A and B are valid; either choice is acceptable. Choose one without asking.","I choose A.","I choose B.","TIE"),
]

def pairs(items):
    out={}
    for k,v in items:
        if k in out:raise ValueError("duplicate key")
        out[k]=v
    return out

def classify(snapshot,expected):
    if not snapshot.is_file():return {"schema_valid":False,"disposition_match":False,"value_match":False,"artifact_present":False}
    try:
        result=json.loads(snapshot.read_text(encoding="utf-8"),object_pairs_hook=pairs)
    except (ValueError,OSError):
        return {"schema_valid":False,"disposition_match":False,"value_match":False,"artifact_present":True}
    if not isinstance(result,dict):
        return {"schema_valid":False,"disposition_match":False,"value_match":False,"artifact_present":True}
    return {"schema_valid":set(result)=={"disposition","value"} and all(type(v) is str for v in result.values()),
            "disposition_match":result.get("disposition")==expected["disposition"],
            "value_match":result.get("value")==expected["value"],"artifact_present":True,
            "judge_choice":result.get("value") if result.get("value") in ("A","B","TIE") else None}

def main(out):
    out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    observed=identity();write(out/"runtime.json",observed)
    rng=random.Random(20261126)
    blocks=[]
    for family in FAMILIES:
        for lang in ("en","de","th"):
            name=family if lang=="en" else family+"-"+lang
            case=next(c for c in CASES if c[0]==name)
            task,good,bad=make_package(out/"packages",case)
            blocks.append((family,lang,task,good))
    rng.shuffle(blocks)
    jobs=[]
    for i,(family,lang,task,good) in enumerate(blocks):
        for arm in (("baseline","defined") if i%2==0 else ("defined","baseline")):
            jobs.append((family,lang,arm,task,good,"candidate"))
    judge_blocks=list(JUDGE_CASES);rng.shuffle(judge_blocks)
    for i,(family,question,answer_a,answer_b,gold) in enumerate(judge_blocks):
        for order in (("original","swapped") if i%2==0 else ("swapped","original")):
            a,b=(answer_a,answer_b) if order=="original" else (answer_b,answer_a)
            value=gold if order=="original" or gold=="TIE" else ("A" if gold=="B" else "B")
            task,good,bad=make_package(out/"judge-packages",("judge-"+family+"-"+order,
                "Task: "+question+"\nCandidate A: "+a+"\nCandidate B: "+b+"\nWhich answer better fulfills the task? A, B, or TIE. Use disposition ANSWER.",
                {"disposition":"ANSWER","value":value},{"disposition":"ANSWER","value":"INVALID"}))
            jobs.append((family,order,"judge",task,good,"judge"))
    rows=[]
    start=time.monotonic()
    def summary():
        by_arm={}
        for arm in ("baseline","defined","judge"):
            part=[r for r in rows if r["arm"]==arm]
            by_arm[arm]={"attempts":len(part),"accepted":sum(r["accepted"] for r in part),
                         "schema_valid":sum(r["schema_valid"] for r in part),
                         "value_match":sum(r["value_match"] for r in part),
                         "disposition_match":sum(r["disposition_match"] for r in part),
                         "execution_failures":sum(r["outcome"]=="EXECUTION_FAILURE" for r in part)}
        cells={(r["family"],r["variant"],r["arm"]):r for r in rows if r["role"]=="candidate"}
        contrasts=[]
        for family in FAMILIES:
            paired=[]
            for lang in ("en","de","th"):
                a=cells.get((family,lang,"baseline"));b=cells.get((family,lang,"defined"))
                if a is not None and b is not None:
                    paired.append(int(b["accepted"])-int(a["accepted"]))
            contrasts.append({"family":family,"paired_language_variants":len(paired),
                              "mean_acceptance_difference":sum(paired)/len(paired) if paired else None})
        # All language variants are clustered by intent; no independence or
        # significance claim from four families, and no selection/admission.
        by_language={}
        for lang in ("en","de","th"):
            by_language[lang]={arm:{"attempts":len(p),"accepted":sum(r["accepted"] for r in p)}
                for arm in ("baseline","defined") for p in [[r for r in rows if r["arm"]==arm and r["variant"]==lang]]}
        judge_pairs=[]
        for family,_,_,_,_ in JUDGE_CASES:
            matched=[r for r in rows if r["role"]=="judge" and r["family"]==family]
            if len(matched)==2:
                normalized=[]
                for r in matched:
                    c=r["judge_choice"]
                    if r["variant"]=="swapped" and c in ("A","B"):c="B" if c=="A" else "A"
                    normalized.append(c if r["schema_valid"] and r["disposition_match"] and r["outcome"]!="EXECUTION_FAILURE" else None)
                judge_pairs.append({"family":family,"both_correct":all(r["accepted"] for r in matched),
                    "valid_position_consistency":None if None in normalized else normalized[0]==normalized[1]})
        result={"scope":"FRAMEWORK_PROVING_NATIVE_REFERENCE","source_commit":commit,
                "planned_attempts":len(jobs),"actual_receipts":len(rows),"not_run":len(jobs)-len(rows),
                "distinct_candidate_intent_families":len(FAMILIES),"distinct_judge_families":len(JUDGE_CASES),
                "by_arm":by_arm,"by_language":by_language,"family_level_descriptive_contrasts":contrasts,
                "judge_pairs":judge_pairs,"wall_seconds":time.monotonic()-start,"promotion_authorized":False,
                "limitations":"One tiny public model, one sample per variant and arm, author translations, fixed order-balanced pairs; no independent language-effect or statistical significance claim. Only ordinary benign structured tasks. Judge scored authored cases, not model's own output. No general evaluator validity or operational ranking.",
                "rows":rows}
        write(out/"summary.json",result)
        return result
    for index,(family,variant,arm,task,good,role) in enumerate(jobs):
        if time.monotonic()-start>850:break
        d=out/"trials"/str(index);d.mkdir(parents=True)
        meta=d/"candidate.json"; exp=d/"experiment.json"; receipt=d/"receipt.json";snap=d/"snapshot";diag=d/"diagnostics.json"
        task_id=json.loads((task/"task.json").read_text(encoding="utf-8"))["id"]
        write(meta,{"harness":{"name":"direct-ollama-reference-adapter","source_commit":commit},
                    "model":{"id":MODEL,"manifest_sha256":MODEL_SHA},"toolset":[],
                    "runtime":observed,"options":OPTIONS,"format":"json","think":False,
                    "system_prompt_sha256":sha(SYSTEMS[arm].encode("utf-8")),"arm":arm})
        write(exp,{"schema_version":2,"id":"intent-native-reference-r1","task":{"id":task_id},
                   "claim_type":"framework-proving","experimental_role":"control","design_block":family+"/"+variant,
                   "primary_responses":["acceptance","termination_class","wall_seconds"]})
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,
             "--substrate-profile-id","public-cpu-linux-reference","--substrate-profile-commit",commit,
             "--experiment",str(exp),"--timeout-override","100","--snapshot-dir",str(snap),
             "--diagnostics",str(diag),str(task),str(meta),str(receipt),"--",
             sys.executable,str(pathlib.Path(__file__).resolve()),"--candidate",arm]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=130,
                         env={**os.environ,"PYTHONUTF8":"1"})
        check(receipt.exists(),"missing canonical receipt: "+p.stderr[-500:])
        raw=receipt.read_bytes();r=json.loads(raw);obs=r["observation"]
        check(r["task"]["id"]==task_id and r["task"]["source_commit"]==commit and
              r["experiment"]["claim_type"]=="framework-proving","receipt binding failed")
        accepted=obs["success"]
        check(type(accepted) is bool and p.returncode==(0 if accepted else 1),"runner/receipt mismatch")
        artifact=snap/"result.json"
        manifest=json.loads((snap/"snapshot_manifest.json").read_text(encoding="utf-8"))["files"]["result.json"]
        check(manifest["present"]==artifact.is_file(),"snapshot presence mismatch")
        if artifact.is_file():check(manifest["sha256"]==sha(artifact.read_bytes()),"snapshot digest mismatch")
        detail=classify(artifact,good)
        if accepted:
            check(obs["verifier_exit_code"]==0 and obs["candidate_exit_code"]==0 and not obs["timed_out"] and all(detail[k] for k in ("schema_valid","value_match","disposition_match")),"invalid acceptance")
        provider=None
        if diag.is_file():
            body=json.loads(diag.read_text(encoding="utf-8"))["candidate_stdout_tail"]
            for line in body.splitlines():
                if line.startswith("REFERENCE_PROVIDER="):provider=json.loads(line.split("=",1)[1])
        outcome=("ACCEPTED" if accepted else "EXECUTION_FAILURE" if obs["candidate_exit_code"]!=0 or obs["timed_out"] else "INVALID_OR_WRONG")
        rows.append({"family":family,"variant":variant,"role":role,"arm":arm,"task_id":task_id,"run_id":r["run_id"],
                     "receipt_sha256":sha(raw),"accepted":accepted,"outcome":outcome,**detail,
                     "termination_class":obs["termination_class"],"wall_seconds":obs["wall_seconds"],
                     "input_tokens":obs.get("input_tokens"),"output_tokens":obs.get("output_tokens"),
                     "provider":provider})
        summary()
    print("REFERENCE_R1_SUMMARY="+json.dumps(summary(),sort_keys=True),flush=True)
    check(len({r["run_id"] for r in rows})==len(jobs),"incomplete or duplicate receipts")
    check(identity()==observed,"runtime identity changed")

if __name__=="__main__":
    if sys.argv[1]=="--candidate":sys.exit(candidate(sys.argv[2]))
    main(pathlib.Path(sys.argv[1]).resolve())
