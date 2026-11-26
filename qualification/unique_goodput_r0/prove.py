"""Framework proof of unique accepted work vs repeated successful attempts.
Uses canonical receipts, a fixed synthetic assignment manifest and measured wrapper time.
No production authority, actual model or scheduler.
"""
import copy
import hashlib
import json
import math
import pathlib
import subprocess
import sys
import time

ROOT=pathlib.Path(__file__).resolve().parents[2]
TASK=ROOT/"qualification/tasks/text-repair-v0"
PLAN=[("a",1,False),("a",2,True),("a",3,True),("b",1,True),("c",1,False)]
ASSIGNMENTS=["a","b","c","d"]  # d explicitly not started
def sha(b):return "sha256:"+hashlib.sha256(b).hexdigest()
def digest(x):return sha(json.dumps(x,sort_keys=True,separators=(",",":")).encode("utf-8"))
def write(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def require(ok,msg):
    if not ok:raise ValueError(msg)
def number(x):return type(x) in (int,float) and math.isfinite(x) and x>=0
def trial(out,index,assignment,attempt,expected,commit):
    d=out/str(index);d.mkdir(parents=True)
    meta={"harness":{"name":"scripted-goodput-control"},"model":{"id":"none"},"toolset":["write_file"],"treatment":"valid" if expected else "invalid"}
    exp={"schema_version":2,"id":"unique-goodput-r0","task":{"id":"text-repair-v0"},"claim_type":"framework-proving","experimental_role":"control","design_block":index,"primary_responses":["acceptance","wall_seconds"]}
    write(d/"candidate.json",meta);write(d/"experiment.json",exp)
    receipt=d/"receipt.json"
    code="from pathlib import Path; Path('value.txt').write_bytes("+repr(b"READY\n" if expected else b"WRONG\n")+")"
    cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,
         "--substrate-profile-id","framework-"+sys.platform,"--substrate-profile-commit",commit,
         "--experiment",str(d/"experiment.json"),str(TASK),str(d/"candidate.json"),str(receipt),
         "--",sys.executable,"-c",code]
    start=time.monotonic()
    p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
    elapsed=time.monotonic()-start
    require(receipt.is_file(),"receipt missing "+p.stderr)
    raw=receipt.read_bytes();r=json.loads(raw)
    require(p.returncode==(0 if expected else 1) and r["observation"]["success"] is expected,"unexpected control outcome")
    return {"index":index,"assignment":assignment,"attempt":attempt,"run_id":r["run_id"],"receipt_sha256":sha(raw),
            "wall_seconds":elapsed,"expected_candidate_digest":digest(meta),"expected_experiment_digest":digest(exp)}
def reduce(rows,raws,elapsed,commit):
    # Plan is fixture-owned, not derived from arriving rows. Deny lost, duplicate or unplanned rows.
    require(number(elapsed) and elapsed>0,"bad campaign elapsed")
    require(len(rows)==len(PLAN) and len(raws)==len(PLAN),"incomplete plan")
    require([row["index"] for row in rows]==list(range(len(PLAN))),"bad attempt order")
    accepted=set();first=set();started=set();seen=set();attempt_success=0;attempt_wall=0
    for i,(row,raw,(assignment,attempt,expected)) in enumerate(zip(rows,raws,PLAN)):
        require((row["assignment"],row["attempt"])==(assignment,attempt),"assignment/attempt mismatch")
        require(row["receipt_sha256"]==sha(raw),"receipt digest mismatch")
        r=json.loads(raw);run=r["run_id"]
        require(row["run_id"]==run and run not in seen,"run identity duplicate/mismatch")
        seen.add(run)
        require(r["task"]["source_commit"]==commit and r["task"]["id"]=="text-repair-v0","source mismatch")
        require(r["experiment"]["claim_type"]=="framework-proving" and r["experiment"]["design_block"]==i,"purpose/block mismatch")
        require(r["experiment"]["digest"]==row["expected_experiment_digest"],"experiment mismatch")
        require(r["candidate"]["configuration_digest"]==row["expected_candidate_digest"],"configuration mismatch")
        require(number(row["wall_seconds"]) and row["wall_seconds"]>0,"bad wrapper measurement")
        obs=r["observation"];success=obs["success"]
        require(type(success) is bool and success is expected,"control verdict mismatch")
        require(number(obs["wall_seconds"]) and obs["wall_seconds"]<=row["wall_seconds"]+0.000001,"bad runner measurement")
        require(not success or (obs["candidate_exit_code"]==0 and obs["verifier_exit_code"]==0 and not obs["timed_out"]),"false success")
        started.add(assignment);attempt_wall+=row["wall_seconds"]
        if success:
            attempt_success+=1;accepted.add(assignment)
            if attempt==1:first.add(assignment)
    require(attempt_wall<=elapsed+0.000001,"serial attempt wall exceeds campaign")
    n=len(accepted)
    return {"scope":"FRAMEWORK_PROVING_ONLY","source_commit":commit,"assigned":len(ASSIGNMENTS),
            "started":len(started),"not_started":len(set(ASSIGNMENTS)-started),"attempts":len(rows),
            "accepted_attempts":attempt_success,"failed_attempts":len(rows)-attempt_success,
            "accepted_unique":n,"first_pass_unique":len(first),"eventual_acceptance_rate":n/len(ASSIGNMENTS),
            "first_pass_rate":len(first)/len(ASSIGNMENTS),"duplicate_success_not_credited":attempt_success-n,
            "attempt_wall_seconds":attempt_wall,"campaign_elapsed_seconds":elapsed,
            "accepted_unique_per_hour":n*3600/elapsed,"campaign_seconds_per_accepted":elapsed/n if n else None,
            "gpu_seconds":None,"energy_joules":None,"human_attention_seconds":None,"promotion_authorized":False,
            "limitations":"Serial synthetic control campaign only; wall includes local wrapper, initialization and verification, not GHA queue/provisioning. No target model, concurrency, cost/energy or production goodput claim."}
def main(out):
    out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    start=time.monotonic()
    rows=[trial(out,i,a,k,expected,commit) for i,(a,k,expected) in enumerate(PLAN)]
    raws=[(out/str(i)/"receipt.json").read_bytes() for i in range(len(rows))]
    elapsed=time.monotonic()-start
    s=reduce(rows,raws,elapsed,commit)
    require((s["assigned"],s["started"],s["accepted_unique"],s["first_pass_unique"],s["accepted_attempts"],s["failed_attempts"])==(4,3,2,1,3,2),"known totals mismatch")
    # Independently planted bookkeeping faults; no change to actual receipts.
    cases=[]
    cases.append(("missing",rows[:-1],raws[:-1],elapsed,commit))
    cases.append(("duplicate",rows[:-1]+[rows[0]],raws[:-1]+[raws[0]],elapsed,commit))
    cases.append(("swapped_receipt",rows,[raws[1],raws[0]]+raws[2:],elapsed,commit))
    bad=copy.deepcopy(rows);bad[0]["assignment"]="d";cases.append(("assignment_alias",bad,raws,elapsed,commit))
    bad=copy.deepcopy(rows);bad[0]["wall_seconds"]=float("nan");cases.append(("unknown_as_number",bad,raws,elapsed,commit))
    bad=copy.deepcopy(rows);bad[0]["expected_experiment_digest"]="sha256:"+"0"*64;cases.append(("experiment_mismatch",bad,raws,elapsed,commit))
    cases.append(("wrong_source",rows,raws,elapsed,"0"*40))
    cases.append(("impossible_serial_elapsed",rows,raws,0.0000001,commit))
    for name,*args in cases:
        try:reduce(*args)
        except ValueError:continue
        raise RuntimeError("planted accounting fault accepted: "+name)
    s["negative_controls_rejected"]=len(cases)
    write(out/"attempts.json",rows);write(out/"summary.json",s)
    print("UNIQUE_GOODPUT="+json.dumps(s),flush=True)
if __name__=="__main__":
    main(pathlib.Path(sys.argv[1]).resolve())
