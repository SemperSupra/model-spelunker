"""Exercise existing purpose gate on actual canonical runner receipts.
ALL records and manifest entries are synthetic. No operational admission or Compass publication.
"""
import copy,json,os,pathlib,subprocess,sys
from prove import ROOT,admit,digest,reduce_receipts
def write(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def main(out):
    out.mkdir();rows=[];labels={}
    commit=os.environ.get("GITHUB_SHA") or subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    # Operational-observation labels are adversarial synthetic fixtures, never authority.
    cases=[("framework-pass","framework-proving",True),("framework-fail","framework-proving",False),("test-op-pass","operational-observation",True),("test-op-fail","operational-observation",False),("unknown","unknown-purpose",True),("legacy",None,True)]
    for label,claim,good in cases:
        d=out/label;d.mkdir()
        meta=d/"candidate.json";write(meta,{"harness":{"name":"synthetic-purpose-control"},"model":{"id":"none"},"toolset":["write_file"]})
        exp=d/"experiment.json"
        if claim is not None:write(exp,{"schema_version":2,"id":"synthetic-purpose-r1","task":{"id":"text-repair-v0"},"claim_type":claim,"experimental_role":"control","primary_responses":["acceptance"]})
        path=d/"receipt.json"
        data=b"READY\n" if good else b"WRONG\n"
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,"--substrate-profile-id","synthetic-public","--substrate-profile-commit",commit]
        if claim is not None:cmd+=["--experiment",str(exp)]
        cmd += [str(ROOT/"qualification/tasks/text-repair-v0"),str(meta),str(path),"--",sys.executable,"-c",f"from pathlib import Path;Path('value.txt').write_bytes({data!r})"]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=60)
        assert path.exists(),p.stderr
        row=json.loads(path.read_bytes());assert row["observation"]["success"] is good
        labels[label]=row["run_id"];rows.append(row)
    # Simulate a bad or overbroad caller manifest trying to mark every receipt operational.
    manifest={r["run_id"]:{"receipt_digest":digest(r),"purpose":"OPERATIONAL_QUALIFICATION"} for r in rows}
    eligible,excluded=admit(rows,manifest)
    assert {r["run_id"] for r in eligible}=={labels["test-op-pass"],labels["test-op-fail"]}
    want={labels["framework-pass"]:"PURPOSE_CONFLICT",labels["framework-fail"]:"PURPOSE_CONFLICT",labels["unknown"]:"PURPOSE_UNKNOWN_OR_LEGACY",labels["legacy"]:"PURPOSE_UNKNOWN_OR_LEGACY"}
    assert {r["run_id"]:r["reason"] for r in excluded}==want
    assert admit(rows,{})[0]==[]
    result=reduce_receipts(eligible)
    assert len(result)==1 and result[0]["evidence"]["reps"]==2
    assert result[0]["evidence"]["validated_pass"]==1 and result[0]["evidence"]["validated_fail"]==1
    assert sum(e["evidence"]["reps"] for e in reduce_receipts(rows))==6
    known=next(r for r in rows if r["run_id"]==labels["test-op-pass"])
    # Same identity with modified content: reject even if valid-looking.
    mutated=copy.deepcopy(known);mutated["observation"]["wall_seconds"]+=1
    assert admit([mutated],manifest)[1][0]["reason"]=="DIGEST_MISMATCH"
    # Matching synthetic digest cannot make an internally inconsistent receipt eligible.
    bad=copy.deepcopy(known);bad["observation"]["success"]="true"
    forged={bad["run_id"]:{"receipt_digest":digest(bad),"purpose":"OPERATIONAL_QUALIFICATION"}}
    assert admit([bad],forged)[1][0]["reason"]=="INVALID_OBSERVATION"
    bad=copy.deepcopy(known);bad["observation"]["verifier_exit_code"]=1
    forged={bad["run_id"]:{"receipt_digest":digest(bad),"purpose":"OPERATIONAL_QUALIFICATION"}}
    assert admit([bad],forged)[1][0]["reason"]=="INVALID_OBSERVATION"
    assert len(admit([known,copy.deepcopy(known)],manifest)[0])==1
    try:admit([known,mutated],manifest)
    except ValueError:pass
    else:raise AssertionError("divergent duplicate admitted")
    summary={"scope":"FRAMEWORK_PROVING_ONLY","actual_canonical_receipts":6,"ungated_reps":6,"hypothetical_eligible":2,"hypothetical_excluded":4,"hypothetical_pass":1,"hypothetical_fail":1,"additional_controls":6,"empty_manifest_eligible":0,"operational_envelopes":[],"promotion_authorized":False,"limitations":"caller manifest is a synthetic test fixture, not authenticated authority; existing production reducer unchanged; all observations synthetic"}
    write(out/"summary.json",summary);write(out/"synthetic-test-reduction.json",{"scope":"FRAMEWORK_PROVING_ONLY","hypothetical_envelopes":result,"operational_envelopes":[]})
    print("PURPOSE_CANONICAL="+json.dumps(summary),flush=True)
if __name__=="__main__":main(pathlib.Path(sys.argv[1]).resolve())
