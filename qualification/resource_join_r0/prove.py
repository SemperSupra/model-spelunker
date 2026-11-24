"""Framework-only Linux proof: resource accounting bound to canonical receipts.
No inference-server or GPU measurement claimed. Reuse #316 phase sources later.
"""
import hashlib,json,math,os,pathlib,resource,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[2]
def sha(raw): return "sha256:"+hashlib.sha256(raw).hexdigest()
def metric(value,unit,source):
    return {"value":value,"unit":unit,"source":source,"status":"OBSERVED" if value is not None else "UNKNOWN"}
def write(p,x): p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n")
def trial(out,arm,rep):
    out.mkdir(parents=True,exist_ok=False)
    receipt=out/"receipt.json"; metadata=out/"candidate.json"; experiment=out/"experiment.json"
    commit=os.environ.get("GITHUB_SHA") or subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    write(metadata,{"harness":{"name":"synthetic-control"},"model":{"id":"none"},"toolset":["write_file"],"treatment":arm})
    write(experiment,{"schema_version":2,"id":"resource-join-r0","task":{"id":"text-repair-v0"},"claim_type":"framework-proving","experimental_role":"control","design_block":rep,"primary_responses":["accepted","cpu_seconds"]})
    # Identical verified output for cheap/expensive; rejected arm also consumes resources.
    loops=10000 if arm=="cheap" else 1400000
    output="WRONG" if arm=="rejected" else "READY"
    candidate=f"from pathlib import Path; import hashlib; x=b'x'\nfor _ in range({loops}): x=hashlib.sha256(x).digest()\nPath('value.txt').write_bytes({(output+chr(10)).encode()!r})"
    cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,"--substrate-profile-id","framework-linux","--substrate-profile-commit",commit,"--experiment",str(experiment),str(ROOT/"qualification/tasks/text-repair-v0"),str(metadata),str(receipt),"--",sys.executable,"-c",candidate]
    before=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.monotonic()
    proc=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=60)
    elapsed=time.monotonic()-start;after=resource.getrusage(resource.RUSAGE_CHILDREN)
    assert receipt.exists(),proc.stderr
    raw=receipt.read_bytes();r=json.loads(raw);accepted=r["observation"]["success"]
    assert accepted==(arm!="rejected")
    # Wrapper is one fresh process per trial, so child peak RSS has no preceding trial.
    cpu=after.ru_utime-before.ru_utime+after.ru_stime-before.ru_stime
    row={"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","run_id":r["run_id"],"receipt_sha256":sha(raw),"source_commit":commit,"treatment":arm,"block":rep,"accepted":accepted,"accounting_scope":"canonical runner and waited child processes; excludes runner provisioning and remote processes","metrics":{"cpu_seconds":metric(cpu,"cpu-s","linux getrusage RUSAGE_CHILDREN delta"),"wall_seconds":metric(elapsed,"s","wrapper monotonic"),"peak_child_rss_bytes":metric(after.ru_maxrss*1024,"B","linux getrusage maxrss; maximum child, not sum or integrated memory"),"gpu_seconds":metric(None,"gpu-s","not instrumented"),"energy_joules":metric(None,"J","not instrumented"),"prefill_seconds":metric(None,"s","no inference in this fixture"),"decode_seconds":metric(None,"s","no inference in this fixture")}}
    write(out/"resource.json",row)
def validate(row,raw):
    r=json.loads(raw)
    if row["receipt_sha256"]!=sha(raw) or row["run_id"]!=r["run_id"] or row["accepted"] is not r["observation"]["success"]:
        raise ValueError("receipt binding mismatch")
    if row["scope"]!="FRAMEWORK_PROVING_ONLY" or r.get("experiment",{}).get("claim_type")!="framework-proving": raise ValueError("purpose mismatch")
    for name,m in row["metrics"].items():
        v=m["value"]
        if m["status"]=="UNKNOWN":
            if v is not None: raise ValueError("unknown must not contain a numeric value")
        elif m["status"]!="OBSERVED" or type(v) not in (int,float) or not math.isfinite(v) or v<0:
            raise ValueError("invalid observed measurement")
    return row
def proof(out):
    out.mkdir(parents=True,exist_ok=True);rows=[]
    orders=[("cheap","expensive","rejected"),("rejected","expensive","cheap"),("expensive","cheap","rejected")]
    for block,order in enumerate(orders):
        for arm in order:
            dest=out/(str(block)+"-"+arm)
            subprocess.run([sys.executable,__file__,"trial",str(dest),arm,str(block)],check=True,timeout=75)
            rows.append(validate(json.loads((dest/"resource.json").read_text()),(dest/"receipt.json").read_bytes()))
    import copy
    raw=(out/"0-cheap"/"receipt.json").read_bytes()
    known=next(r for r in rows if r["block"]==0 and r["treatment"]=="cheap")
    def negative(change):
        a=copy.deepcopy(known);change(a)
        try:validate(a,raw)
        except ValueError:return True
        return False
    assert negative(lambda a:a.update(receipt_sha256="wrong"))
    assert negative(lambda a:a.update(accepted=False))
    assert negative(lambda a:a["metrics"]["energy_joules"].update(value=0))
    assert negative(lambda a:a["metrics"]["cpu_seconds"].update(value=float("nan")))
    assert len({r["run_id"] for r in rows})==9
    groups={}
    for arm in ("cheap","expensive","rejected"):
        v=[r for r in rows if r["treatment"]==arm]
        accepted=sum(r["accepted"] for r in v);cpu=sum(r["metrics"]["cpu_seconds"]["value"] for r in v)
        groups[arm]={"attempts":len(v),"accepted":accepted,"cpu_seconds":cpu,"wall_seconds":sum(r["metrics"]["wall_seconds"]["value"] for r in v),"cpu_seconds_per_accepted":cpu/accepted if accepted else None}
    assert groups["expensive"]["cpu_seconds"]>groups["cheap"]["cpu_seconds"]
    assert groups["rejected"]["cpu_seconds"]>0 and groups["rejected"]["accepted"]==0
    totalcpu=sum(v["cpu_seconds"] for v in groups.values());good=sum(v["accepted"] for v in groups.values())
    result={"scope":"FRAMEWORK_PROVING_ONLY","rows":len(rows),"groups":groups,"all_attempt_cpu_seconds":totalcpu,"all_attempt_cpu_seconds_per_accepted":totalcpu/good,"negative_controls":4,"gpu_energy_prefill_decode":"UNKNOWN","status":"PASS"}
    write(out/"summary.json",result);print("RESOURCE_JOIN="+json.dumps(result),flush=True)
if __name__=="__main__":
    if sys.argv[1]=="trial":trial(pathlib.Path(sys.argv[2]).resolve(),sys.argv[3],int(sys.argv[4]))
    else:proof(pathlib.Path(sys.argv[2]).resolve())
