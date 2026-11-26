"""Actual canonical task-conditioned control observations and separate fixture confirmation.
Task packages are public; confirmation fixtures are distinct, not secret or operational holdout.
"""
import hashlib,json,os,pathlib,random,resource,subprocess,sys,time
HERE=pathlib.Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"qualification"))
from reduce_evidence import reduce_receipts
ARMS=("repair","lookup","composite")
def write(p,x):p.write_text(json.dumps(x,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def main(out):
    out.mkdir();rows=[];receipts=[];rng=random.Random(1411)
    commit=os.environ["GITHUB_SHA"]
    tasks={"screen":{"repair":ROOT/"qualification/tasks/text-repair-v0","lookup":HERE/"task_controls/lookup-screen-r1"},"confirm":{"repair":HERE/"task_controls/repair-confirm-r1","lookup":HERE/"task_controls/lookup-confirm-r1"}}
    for task in [p for stage in tasks.values() for p in stage.values()]:
        subprocess.run([sys.executable,str(task/"verify.py"),"--self-test"],check=True,timeout=15)
    def trial(stage,family,block,arm):
        task=tasks[stage][family];meta=json.loads((task/"task.json").read_text())
        dest=out/f"{stage}-{family}-{block}-{arm}";dest.mkdir()
        candidate=dest/"candidate.json";write(candidate,{"harness":{"name":"scripted-"+arm},"model":{"id":"none"},"toolset":["read_file","write_file"],"control_arm":arm})
        experiment=dest/"experiment.json";write(experiment,{"schema_version":2,"id":"task-conditioned-r1","task":{"id":meta["id"]},"claim_type":"framework-proving","experimental_role":"control","design_block":f"{stage}-{family}-{block}","primary_responses":["acceptance","cpu_seconds"]})
        receipt=dest/"receipt.json"
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,"--substrate-profile-id","framework-public-linux","--substrate-profile-commit",commit,"--experiment",str(experiment),str(task),str(candidate),str(receipt),"--",sys.executable,str(HERE/"task_control_candidate.py"),arm]
        before=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.monotonic()
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=60)
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        assert receipt.exists(),p.stderr
        raw=receipt.read_bytes();r=json.loads(raw);expected=arm in (family,"composite")
        assert r["observation"]["success"] is expected
        assert r["task"]["id"]==meta["id"] and r["task"]["task_class"]==meta["task_class"]
        assert r["experiment"]["claim_type"]=="framework-proving"
        row={"stage":stage,"family":family,"task_id":meta["id"],"task_class":meta["task_class"],"block":block,"arm":arm,"run_id":r["run_id"],"receipt_sha256":"sha256:"+hashlib.sha256(raw).hexdigest(),"accepted":expected,"cpu_seconds":after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,"wall_seconds":time.monotonic()-start}
        write(dest/"measurement.json",row);rows.append(row);receipts.append(r)
    def phase(stage):
        for block in range(2):
            cells=[(family,arm) for family in ("repair","lookup") for arm in ARMS];rng.shuffle(cells)
            for family,arm in cells:trial(stage,family,block,arm)
    phase("screen")
    decisions={}
    for family in ("repair","lookup"):
        scores={arm:[r for r in rows if r["family"]==family and r["arm"]==arm] for arm in ARMS}
        eligible=[arm for arm,v in scores.items() if len(v)==2 and all(r["accepted"] for r in v)]
        assert set(eligible)=={family,"composite"}
        decisions[family]={"eligible":sorted(eligible),"selected":min(eligible,key=lambda a:sum(r["cpu_seconds"] for r in scores[a]))}
    write(out/"selection-before-confirmation.json",{"scope":"FRAMEWORK_PROVING_ONLY","decisions":decisions,"promotion_authorized":False})
    phase("confirm")
    assert len(rows)==24 and len({r["run_id"] for r in rows})==24
    for family,decision in decisions.items():
        selected=[r for r in rows if r["stage"]=="confirm" and r["family"]==family and r["arm"]==decision["selected"]]
        assert len(selected)==2 and all(r["accepted"] for r in selected)
    envelopes=reduce_receipts(receipts)
    assert len(envelopes)==6
    assert all(e["evidence"]["reps"]==4 and e["evidence"]["unique_task_instances"]==2 for e in envelopes)
    # Preserve raw reducer output as a labeled scientific projection, never an operational envelope.
    write(out/"framework-reduction.json",{"scope":"FRAMEWORK_PROVING_ONLY","hypothetical_envelopes":envelopes,"operational_envelopes":[]})
    by={}
    for arm in ARMS:
        by[arm]={family:{"attempts":len(v),"accepted":sum(x["accepted"] for x in v),"cpu_seconds":sum(x["cpu_seconds"] for x in v)} for family in ("repair","lookup") if (v:=[x for x in rows if x["arm"]==arm and x["family"]==family])}
    assert by["repair"]["repair"]["accepted"]==4 and by["repair"]["lookup"]["accepted"]==0
    assert by["lookup"]["repair"]["accepted"]==0 and by["lookup"]["lookup"]["accepted"]==4
    result={"scope":"FRAMEWORK_PROVING_ONLY","task_families":2,"task_packages":4,"attempts":24,"accepted":sum(r["accepted"] for r in rows),"task_conditioned_groups":6,"confirmed_selections":4,"decisions":decisions,"by_arm":by,"rows":rows,"promotion_authorized":False,"limitations":"scripted controls intentionally specialized; two distinct public fixture instances per family, not realistic benchmark or secret holdout; measured waited-child CPU excludes setup and remote resources"}
    write(out/"summary.json",result);print("TASK_STRATA="+json.dumps({k:v for k,v in result.items() if k!="rows"}),flush=True)
if __name__=="__main__":main(pathlib.Path(sys.argv[1]).resolve())
