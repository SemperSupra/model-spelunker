"""Judge-interface calibration, public authored benign tasks only.

The same public reference model and fixed pairs are used with two ordinary
JSON output contracts. The model sees no gold labels and does not judge its own
answers. A separate deterministic oracle checks final artifacts.
"""
import importlib.util
import json
import math
import os
import pathlib
import random
import resource
import subprocess
import sys
import tempfile
import time

HERE=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("intent_reference",HERE/"prove.py")
ref=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)
ROOT=ref.ROOT
ARMS=("json","typed")
CHOICES=("A","B","TIE","NEITHER")
SCHEMA={"type":"object","properties":{"choice":{"type":"string","enum":list(CHOICES)}},"required":["choice"],"additionalProperties":False}
SYSTEM=("Compare the two answers to the stated benign task. A or B if that answer alone better satisfies the task; "
        "TIE if both satisfy it equally; NEITHER if neither satisfies the mandatory requirements. "
        "Do not favor length or position. Return exactly one JSON field, choice, whose string is A, B, TIE, or NEITHER.")
# Disjoint from R1 calibration fixtures; public authored confirmation controls,
# not secret or independently human-reviewed holdout.
CONFIRM=[
 ("conf-count","There are 9 books and 2 are removed. Return the remaining count.","7","11","A"),
 ("conf-revision","The current shipment label is ORANGE, superseding SILVER. Return the current label.","SILVER","ORANGE","B"),
 ("conf-unknown","The record does not specify the temperature. Do not guess.","The temperature is unknown.","It is 20 degrees.","A"),
 ("conf-format","Respond with exactly the single word PDF.","The format is PDF.","PDF","B"),
 ("conf-equal","Either an integer or a sentence is acceptable. What is 6 minus 2?","4","The answer is four.","TIE"),
 ("conf-neither","Return exactly the word DONE.","COMPLETE","Done, as requested.","NEITHER"),
]
VERIFIER=r'''
import json,pathlib,sys,tempfile
FIXTURE=__FIXTURE__
EXPECTED=__EXPECTED__
def pairs(items):
    d={}
    for k,v in items:
        if k in d:raise ValueError("duplicate key")
        d[k]=v
    return d
def verify(root):
    try:
        if {p.name for p in root.iterdir()}!={"intent.json","result.json"}:return False
        for p in root.iterdir():
            if p.is_symlink() or not p.is_file() or p.stat().st_size>16384:return False
        if (root/"intent.json").read_bytes()!=FIXTURE:return False
        return json.loads((root/"result.json").read_text(encoding="utf-8"),object_pairs_hook=pairs)=={"choice":EXPECTED}
    except (OSError,ValueError,TypeError):return False
if __name__=="__main__":sys.exit(0 if verify(pathlib.Path(sys.argv[1])) else 1)
'''
def swap(c):return {"A":"B","B":"A"}.get(c,c)
def pairs(items):
    result={}
    for k,v in items:
        if k in result:raise ValueError("duplicate key")
        result[k]=v
    return result
def choice(raw):
    try:
        doc=json.loads(raw,object_pairs_hook=pairs)
        if type(doc) is dict and set(doc)=={"choice"} and type(doc["choice"]) is str and doc["choice"] in CHOICES:
            return doc["choice"]
    except (TypeError,ValueError,UnicodeDecodeError):pass
    return None
def package(out,stage,case,order):
    family,question,a,b,gold=case
    if order=="swapped":a,b,gold=b,a,swap(gold)
    task=out/"packages"/stage/(family+"-"+order)
    (task/"fixture").mkdir(parents=True)
    prompt=f"Task: {question}\nCandidate A: {a}\nCandidate B: {b}\nEvaluate the answers using the stated criteria."
    ref.write(task/"fixture/intent.json",{"scenario":prompt})
    fixture=(task/"fixture/intent.json").read_bytes()
    (task/"verify.py").write_text(VERIFIER.replace("__FIXTURE__",repr(fixture)).replace("__EXPECTED__",repr(gold)),encoding="utf-8")
    ref.write(task/"task.json",{"schema_version":1,"id":"judge-"+stage+"-"+family+"-"+order+"-v0","task_class":"framework.judge-calibration",
        "instruction":prompt,"fixture":"fixture","verifier":"verify.py","limits":{"wall_seconds":100},
        "success":{"kind":"deterministic-final-state"},"allowed_write_paths":["result.json"],"projected_tools":[]})
    return task,gold
def candidate(arm):
    prompt=sys.stdin.read()
    payload={"model":ref.MODEL,"stream":False,"think":False,"format":SCHEMA if arm=="typed" else "json","options":ref.OPTIONS,
             "messages":[{"role":"system","content":SYSTEM},{"role":"user","content":prompt}]}
    t=time.monotonic()
    try:
        r=ref.request("/api/chat",payload,timeout=90)
        result=r["message"]["content"]
        if not isinstance(result,str) or len(result.encode("utf-8"))>16384:raise ValueError("response bound")
        pathlib.Path("result.json").write_bytes(result.encode("utf-8"))
        print("MODEL_SPELUNKER_USAGE="+json.dumps({"input":r.get("prompt_eval_count"),"output":r.get("eval_count")}),flush=True)
        print("JUDGE_PROVIDER="+json.dumps({"done":r.get("done"),"done_reason":r.get("done_reason"),
              "total_duration_ns":r.get("total_duration"),"load_duration_ns":r.get("load_duration"),
              "prompt_eval_duration_ns":r.get("prompt_eval_duration"),"eval_duration_ns":r.get("eval_duration"),
              "adapter_wall_seconds":time.monotonic()-t}),flush=True)
        return 0 if r.get("done") is True and r.get("done_reason")=="stop" else 3
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print("JUDGE_PROVIDER_ERROR="+type(exc).__name__,flush=True);return 2
def cpu_child():
    r=resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime+r.ru_stime
def cgroup_identity():
    try:
        pid=int(subprocess.check_output(["docker","inspect","--format","{{.State.Pid}}","intent-reference-r0"],text=True,timeout=10).strip())
        rel=next(line[3:] for line in pathlib.Path(f"/proc/{pid}/cgroup").read_text().splitlines() if line.startswith("0::"))
        root=pathlib.Path("/sys/fs/cgroup").resolve()
        path=(root/rel.lstrip("/")).resolve()
        if path==root or root not in path.parents:return None
        return (pid,path)
    except (OSError,ValueError,StopIteration,subprocess.SubprocessError):return None
def cg_cpu(cg):
    if cg is None:return None
    try:
        pid,path=cg
        lines=pathlib.Path(f"/proc/{pid}/cgroup").read_text().splitlines()
        current=next(x[3:] for x in lines if x.startswith("0::"))
        if (pathlib.Path("/sys/fs/cgroup")/current.lstrip("/")).resolve()!=path:return None
        data=dict(line.split() for line in (path/"cpu.stat").read_text().splitlines())
        return int(data["usage_usec"])/1e6
    except (OSError,ValueError,KeyError,StopIteration):return None
def metric(v,unit,source):
    return {"value":v,"unit":unit,"source":source,"status":"OBSERVED" if v is not None else "UNKNOWN"}
def sum_observed(part,name):
    vals=[r["resource"][name]["value"] for r in part]
    return sum(vals) if vals and all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in vals) else None
def summarize(rows,planned,start,commit,identity,controls):
    groups={}
    for stage in ("calibration","confirmation"):
        for arm in ARMS:
            part=[r for r in rows if r["stage"]==stage and r["arm"]==arm]
            pairs_out=[]
            for family in sorted({r["family"] for r in part}):
                p={r["order"]:r for r in part if r["family"]==family}
                if len(p)!=2:continue
                a,b=p["original"],p["swapped"]
                valid=a["choice"] is not None and b["choice"] is not None and a["completed"] and b["completed"]
                pairs_out.append({"family":family,"valid_pair":valid,
                  "position_consistent":a["choice"]==swap(b["choice"]) if valid else None,
                  "both_correct":a["accepted"] and b["accepted"]})
            n=sum(r["accepted"] for r in part)
            costs={name:sum_observed(part,name) for name in ("wrapper_wall_seconds","waited_child_cpu_seconds","server_cgroup_cpu_seconds")}
            groups[stage+"/"+arm]={"attempts":len(part),"strict_accepted":n,
              "valid_completed_choices":sum(r["choice"] is not None and r["completed"] for r in part),
              "execution_failures":sum(not r["completed"] for r in part),
              "tie_or_neither_expected":sum(r["gold"] in ("TIE","NEITHER") for r in part),
              "tie_or_neither_correct":sum(r["accepted"] and r["gold"] in ("TIE","NEITHER") for r in part),
              "false_accept_neither":sum(r["gold"]=="NEITHER" and r["completed"] and r["choice"] in ("A","B","TIE") for r in part),
              "paired_cases":len(pairs_out),"both_correct_pairs":sum(r["both_correct"] for r in pairs_out),
              "position_consistent_valid_pairs":sum(r["position_consistent"] is True for r in pairs_out),
              "unknown_position_pairs":sum(r["position_consistent"] is None for r in pairs_out),
              "pairs":pairs_out,"all_attempt_cost":costs,
              "cost_per_accepted_judgment":{k:v/n if n and v is not None else None for k,v in costs.items()}}
    return {"scope":"FRAMEWORK_PROVING_NATIVE_JUDGE","source_commit":commit,"runtime":identity,
            "planned_attempts":planned,"actual_receipts":len(rows),"not_run":planned-len(rows),
            "calibration_families":len(ref.JUDGE_CASES),"confirmation_families":len(CONFIRM),
            "negative_oracle_controls":controls,"groups":groups,"campaign_elapsed_seconds":time.monotonic()-start,
            "promotion_authorized":False,"limitations":"One small reference model; public authored cases, no independent human review or secret holdout, no self-judging. Two orderings per family are dependent. JSON versus typed output changes format interface only, not safety or model weights. Cost excludes cloud provisioning; waited-child CPU excludes server; server cgroup scope includes server background activity when observable. Unknown costs not zero; no operational ranking or statistical inference.","rows":rows}
def main(out):
    out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    ident=ref.identity();ref.write(out/"runtime.json",ident)
    cg=cgroup_identity()
    rng=random.Random(20261126);jobs=[]
    for stage,cases in (("calibration",ref.JUDGE_CASES),("confirmation",CONFIRM)):
        cases=list(cases);rng.shuffle(cases)
        for i,case in enumerate(cases):
            for j,order in enumerate(("original","swapped") if i%2==0 else ("swapped","original")):
                task,gold=package(out,stage,case,order)
                for arm in (ARMS if (i+j)%2==0 else tuple(reversed(ARMS))):
                    jobs.append((stage,case[0],order,arm,task,gold))
    ref.write(out/"plan.json",{"source_commit":commit,"cells":[{"stage":s,"family":f,"order":o,"arm":a,"task_id":json.loads((t/"task.json").read_text())["id"]} for s,f,o,a,t,g in jobs],"system_sha256":ref.sha(SYSTEM.encode()),"schema":SCHEMA,"options":ref.OPTIONS})
    # Run the same independent task oracle outside the actor on a gold and six
    # planted bad artifacts before allowing any live judgments.
    task=jobs[0][4];gold=jobs[0][5]
    bad=[b"{}",b'{"choice":"INVALID"}',b'{"choice":1}',b'{"choice":"A","choice":"A"}',
         json.dumps({"choice":gold,"extra":True}).encode(),json.dumps({"choice":next(c for c in CHOICES if c!=gold)}).encode()]
    with tempfile.TemporaryDirectory() as tmp:
        p=pathlib.Path(tmp);(p/"intent.json").write_bytes((task/"fixture/intent.json").read_bytes())
        def verdict(raw):
            (p/"result.json").write_bytes(raw)
            return subprocess.run([sys.executable,str(task/"verify.py"),str(p)],capture_output=True,timeout=10).returncode
        ref.check(verdict(json.dumps({"choice":gold}).encode())==0,"oracle gold rejected")
        for raw in bad:ref.check(verdict(raw)==1,"oracle bad accepted")
    rows=[];start=time.monotonic()
    for i,(stage,family,order,arm,task,gold) in enumerate(jobs):
        if time.monotonic()-start>850:break
        d=out/"trials"/str(i);d.mkdir(parents=True)
        meta=d/"candidate.json";exp=d/"experiment.json";receipt=d/"receipt.json";snap=d/"snapshot";diag=d/"diagnostics.json"
        task_id=json.loads((task/"task.json").read_text())["id"]
        ref.write(meta,{"harness":{"name":"direct-ollama-judge-calibration","source_commit":commit},"model":{"id":ref.MODEL,"manifest_sha256":ref.MODEL_SHA},
                        "toolset":[],"runtime":ident,"options":ref.OPTIONS,"format":SCHEMA if arm=="typed" else "json","think":False,
                        "system_prompt_sha256":ref.sha(SYSTEM.encode())})
        ref.write(exp,{"schema_version":2,"id":"judge-interface-r2","task":{"id":task_id},"claim_type":"framework-proving",
                       "experimental_role":"control","design_block":stage+"/"+family+"/"+order,"primary_responses":["acceptance","termination_class","wall_seconds"]})
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,"--substrate-profile-id","public-cpu-linux-reference",
             "--substrate-profile-commit",commit,"--experiment",str(exp),"--snapshot-dir",str(snap),"--diagnostics",str(diag),
             str(task),str(meta),str(receipt),"--",sys.executable,str(pathlib.Path(__file__).resolve()),"--candidate",arm]
        before=cpu_child();c0=cg_cpu(cg);t0=time.monotonic()
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=130,env={**os.environ,"PYTHONUTF8":"1"})
        elapsed=time.monotonic()-t0;c1=cg_cpu(cg);child=cpu_child()-before
        ref.check(receipt.exists(),"canonical receipt missing")
        raw=receipt.read_bytes();r=json.loads(raw);obs=r["observation"]
        ref.check(r["task"]["id"]==task_id and r["task"]["source_commit"]==commit and r["experiment"]["claim_type"]=="framework-proving","receipt binding")
        artifact=snap/"result.json";manifest=json.loads((snap/"snapshot_manifest.json").read_text())["files"]["result.json"]
        ref.check(manifest["present"]==artifact.is_file(),"presence mismatch")
        actual=None
        if artifact.is_file():
            data=artifact.read_bytes();ref.check(manifest["sha256"]==ref.sha(data),"snapshot digest");actual=choice(data)
        completed=obs["candidate_exit_code"]==0 and not obs["timed_out"]
        accepted=obs["success"]
        ref.check(type(accepted) is bool and accepted==(completed and actual==gold) and p.returncode==(0 if accepted else 1),"independent judgment mismatch")
        provider=None
        if diag.is_file():
            for line in json.loads(diag.read_text())["candidate_stdout_tail"].splitlines():
                if line.startswith("JUDGE_PROVIDER="):provider=json.loads(line.split("=",1)[1])
        costs={"wrapper_wall_seconds":metric(elapsed,"s","monotonic wrapper includes verifier"),
               "waited_child_cpu_seconds":metric(child,"cpu-s","getrusage RUSAGE_CHILDREN delta, excludes server"),
               "server_cgroup_cpu_seconds":metric(c1-c0 if c0 is not None and c1 is not None and c1>=c0 else None,"cpu-s","container cgroup v2 usage_usec delta"),
               "energy_joules":metric(None,"J","not instrumented")}
        rows.append({"stage":stage,"family":family,"order":order,"arm":arm,"gold":gold,"choice":actual,"completed":completed,
                     "accepted":accepted,"task_id":task_id,"run_id":r["run_id"],"receipt_sha256":ref.sha(raw),
                     "artifact_sha256":manifest.get("sha256"),"termination_class":obs["termination_class"],"provider":provider,"resource":costs})
        ref.write(out/"summary.json",summarize(rows,len(jobs),start,commit,ident,len(bad)))
    result=summarize(rows,len(jobs),start,commit,ident,len(bad));ref.write(out/"summary.json",result)
    print("JUDGE_R2="+json.dumps({k:v for k,v in result.items() if k!="rows"},sort_keys=True),flush=True)
    ref.check(len({r["run_id"] for r in rows})==len(jobs),"incomplete or duplicate receipts")
    ref.check(ref.identity()==ident,"runtime identity changed")
    if cg is not None:ref.check(cgroup_identity()==cg,"server cgroup identity changed")
if __name__=="__main__":
    if sys.argv[1]=="--candidate":sys.exit(candidate(sys.argv[2]))
    main(pathlib.Path(sys.argv[1]).resolve())
