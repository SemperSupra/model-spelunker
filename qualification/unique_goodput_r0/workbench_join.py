"""Exercise exact existing workbench + selection + admission against actual receipts.
No replacement planner, selector, workbench, reducer, or admission authority.
"""
import json,os,pathlib,shutil,subprocess,sys,math
import prove as unique
from composition import load, PURPOSE_HEAD, RESOURCE_HEAD
WORKBENCH_HEAD="ff176a3e3616b725fc48c71c3ee130f6ec350baa"

def check(ok,msg):
    if not ok:raise RuntimeError(msg)
def call(args,**kw):
    return subprocess.check_output(args,text=True,timeout=120,**kw)
def main(evidence,composition,purpose_root,resource_root,wb,out):
    out.mkdir(parents=True,exist_ok=False)
    check(call(["git","-C",str(wb),"rev-parse","HEAD"]).strip()==WORKBENCH_HEAD,"workbench source drift")
    purpose=load("peer_purpose",purpose_root,PURPOSE_HEAD,"qualification/actor_doe_evidence_r0/prove.py")
    resource=load("peer_resource",resource_root,RESOURCE_HEAD,"qualification/resource_join_r0/prove.py")
    view=load("peer_workbench",wb,WORKBENCH_HEAD,"qualification/workbench_r0/workbench.py")
    projection=load("peer_resource_view",wb,WORKBENCH_HEAD,"qualification/workbench_r0/resource_view.py")
    selector=load("peer_selector",wb,WORKBENCH_HEAD,"qualification/workbench_r0/finite_selector.py")
    cli=wb/"qualification/workbench_r0/workbench.py"
    attempts=json.loads((evidence/"attempts.json").read_text())
    comp=json.loads((composition/"summary.json").read_text())
    measured=json.loads((composition/"measurement-rows.json").read_text())
    # Existing workbench shows attempt outcomes. Do not reinterpret three
    # successful attempts as three unique deliverables.
    receipts=out/"unique-receipts";resources=out/"unique-resources"
    receipts.mkdir();resources.mkdir()
    for i,(a,m) in enumerate(zip(attempts,measured)):
        raw=(evidence/str(i)/"receipt.json").read_bytes()
        check(a["receipt_sha256"]==m["receipt_sha256"]==unique.sha(raw),"binding")
        shutil.copyfile(evidence/str(i)/"receipt.json",receipts/(str(i)+".json"))
        mm=m["metrics"]
        metrics={}
        for k,unit in projection.UNITS.items():
            metrics[k]=mm[k] if k in mm else {"value":None,"unit":unit,"source":"not observed by this wrapper","status":"UNKNOWN"}
        side={"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","run_id":m["run_id"],
              "receipt_sha256":m["receipt_sha256"],"accepted":m["accepted"],"accounting_scope":projection.SCOPE,
              "metrics":metrics}
        unique.write(resources/(str(i)+".json"),side)
    actual=view.load(receipts);projection.attach(actual,resources)
    check(actual["summary"]=={"total":5,"accepted":3,"not_accepted":2},"attempt projection")
    check(actual["resources"]["covered"]==5 and actual["resources"]["cpu_coverage"]==5,"resource coverage")
    check(math.isclose(actual["resources"]["cpu_seconds"],comp["costs"]["cpu_seconds"]["all_attempt_total"],rel_tol=1e-12,abs_tol=1e-12),"CPU mismatch")
    check(comp["accepted_unique"]==2 and comp["accepted_attempts"]==3,"unique accounting")
    status=json.loads(call([sys.executable,str(cli),"status","--receipts",str(receipts),"--resources",str(resources)]))
    check(status==actual,"human/automation projection parity")
    rendered=json.loads(call([sys.executable,str(cli),"render","--receipts",str(receipts),"--resources",str(resources),"--output",str(out/"attempt-view.html")]))
    check(rendered["summary"]==actual["summary"],"render mismatch")
    # Execute the exact existing adaptive experiment; explicit source SHA
    # prevents the peer runner from inheriting the outer workflow commit.
    adaptive=out/"adaptive"
    env={**os.environ,"GITHUB_SHA":WORKBENCH_HEAD}
    proc=subprocess.run([sys.executable,str(wb/"qualification/workbench_r0/adaptive_proof.py"),str(adaptive),"exact"],
                        cwd=wb,env=env,capture_output=True,text=True,timeout=160)
    (out/"adaptive-stdout.txt").write_text(proc.stdout,encoding="utf-8")
    (out/"adaptive-stderr.txt").write_text(proc.stderr,encoding="utf-8")
    check(proc.returncode==0,"peer adaptive proof failed "+proc.stderr[-500:])
    s=json.loads((adaptive/"summary.json").read_text());rows=s["rows"]
    check(s["scope"]=="FRAMEWORK_PROVING_ONLY" and s["promotion_authorized"] is False and len(rows)==15,"adaptive scope/count")
    plan=json.loads((adaptive/"selection-before-confirmation.json").read_text())
    screen={}
    all_receipts=[];cpu=0.0;seen=set()
    for row in rows:
        name=f'{row["stage"]}-{row["block"]}-{row["arm"]}'
        raw=(adaptive/"receipts"/(name+".json")).read_bytes()
        side=json.loads((adaptive/"resources"/(name+".json")).read_text())
        r=json.loads(raw);resource.validate(side,raw)
        check(r["task"]["source_commit"]==WORKBENCH_HEAD and r["experiment"]["claim_type"]=="framework-proving","peer receipt source")
        check(r["run_id"]==row["run_id"]==side["run_id"] and r["run_id"] not in seen and row["receipt_sha256"]==unique.sha(raw),"peer receipt binding")
        check(row["accepted"] is side["accepted"] and row["cpu_seconds"]==side["metrics"]["cpu_seconds"]["value"],"peer measurement")
        seen.add(r["run_id"]);all_receipts.append(r);cpu+=row["cpu_seconds"]
        if row["stage"]=="screen":
            acc,cost=screen.get(row["arm"],(0,0.0));screen[row["arm"]]=(acc+int(row["accepted"]),cost+row["cpu_seconds"])
    check({k:list(v) for k,v in screen.items()}==plan["screen_scores"],"selection inputs")
    front=selector.exact(screen)
    check(front==plan["pareto"],"selector mismatch")
    eligible=[a for a in front if screen[a][0]==3]
    check(bool(eligible) and min(eligible,key=lambda a:screen[a][1])==plan["candidate"],"acceptance-gated selection")
    check(math.isclose(cpu,s["all_attempt_cpu_seconds"],rel_tol=1e-12,abs_tol=1e-12),"adaptive total")
    # Intentionally overbroad fixture manifest must not promote any of the
    # actual framework receipts, including the apparent selection winner.
    manifest={r["run_id"]:{"receipt_digest":purpose.digest(r),"purpose":"OPERATIONAL_QUALIFICATION"} for r in all_receipts}
    admitted,excluded=purpose.admit(all_receipts,manifest)
    check(not admitted and len(excluded)==15 and all(x["reason"]=="PURPOSE_CONFLICT" for x in excluded),"framework escape")
    check(purpose.reduce_receipts(admitted)==[],"operational envelope")
    # Existing exact selector must reject unknown costs, not silently score zero.
    rejected=False
    try:selector.exact({**screen,"unknown":(3,None)})
    except ValueError:rejected=True
    check(rejected,"unknown cost admitted")
    result={"scope":"FRAMEWORK_PROVING_ONLY","workbench_head":WORKBENCH_HEAD,
      "unique_receipts_reused":5,"attempt_accepted":3,"unique_accepted":2,
      "attempt_cpu_per_accepted":actual["resources"]["cpu_seconds_per_accepted"],
      "unique_cpu_per_accepted":comp["costs"]["cpu_seconds"]["per_unique_accepted"],
      "adaptive_receipts":len(rows),"adaptive_accepted":s["accepted"],"all_attempt_cpu_seconds":cpu,
      "screen":plan,"confirmation":s["confirmation"],"purpose_conflicts":len(excluded),
      "unknown_cost_rejected":rejected,"operational_envelopes":[],"promotion_authorized":False,
      "limitations":"Exact peer proof and read-only render reused, fixed synthetic task and repeated blocks, not distinct semantic holdout or operational selection. Attempt and unique denominators distinct. No authenticated authority."}
    unique.write(out/"summary.json",result);print("WORKBENCH_JOIN="+json.dumps(result,sort_keys=True),flush=True)
if __name__=="__main__":main(*(pathlib.Path(a).resolve() for a in sys.argv[1:]))
