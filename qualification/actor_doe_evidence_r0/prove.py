"""Prove an explicit evidence-purpose admission seam before existing reduction.
The caller-supplied admission manifest is a trusted test fixture, not authentication.
Never automatically promotes a receipt or establishes actual actor qualification.
"""
import copy, hashlib, json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"qualification"))
from reduce_evidence import reduce_receipts

def digest(x):
    return "sha256:"+hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def admit(rows,manifest):
    """Only caller-admitted operational scope and exact receipt binding.
    Unknown/legacy observations are retained but excluded, not rewritten.
    """
    accepted=[];excluded=[];seen={}
    for r in rows:
        rid=r["run_id"];d=digest(r)
        if rid in seen:
            if seen[rid]!=d: raise ValueError("divergent duplicate run id")
            continue
        seen[rid]=d
        entry=manifest.get(rid)
        if entry is None: reason="UNADMITTED"
        elif entry.get("receipt_digest")!=d: reason="DIGEST_MISMATCH"
        elif entry.get("purpose")!="OPERATIONAL_QUALIFICATION": reason="NON_OPERATIONAL_OR_UNKNOWN"
        elif (r.get("experiment") or {}).get("claim_type")=="framework-proving": reason="PURPOSE_CONFLICT"
        else:
            accepted.append(r);continue
        excluded.append({"run_id":rid,"receipt_digest":d,"reason":reason})
    return accepted,excluded

def sample(rid,claim,success=True,configuration="A",task="test"):
    return {"schema_version":2,"run_id":rid,"task":{"id":task,"task_class":"software.bounded-repair","package_digest":"sha256:"+"a"*64},"candidate":{"harness":{"name":"synthetic-control"},"model":{"id":"none"},"configuration_digest":digest(configuration),"toolset":[]},"substrate":{"profile_id":"synthetic","profile_commit":"f"*40},"experiment":{"claim_type":claim},"observation":{"success":success,"termination_class":"semantic-success" if success else "semantic-failure","candidate_exit_code":0,"verifier_exit_code":0 if success else 1,"state_changed":True,"timed_out":False},"evidence_digest":"sha256:"+"b"*64}

def main():
    out=pathlib.Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    framework=sample("framework","framework-proving")
    operational=sample("op-pass","operational-observation")
    failure=sample("op-fail","operational-observation",False)
    legacy=sample("legacy","unknown");legacy.pop("experiment")
    conflict=sample("conflict","framework-proving")
    stale=sample("stale","operational-observation")
    manifest={r["run_id"]:{"purpose":"OPERATIONAL_QUALIFICATION","receipt_digest":digest(r)} for r in [operational,failure,conflict,stale]}
    manifest["framework"]={"purpose":"FRAMEWORK_PROVING_ONLY","receipt_digest":digest(framework)}
    stale["observation"]["success"]=False
    rows=[framework,operational,failure,legacy,conflict,stale,copy.deepcopy(operational)]
    accepted,excluded=admit(rows,manifest)
    assert {r["run_id"] for r in accepted}=={"op-pass","op-fail"}
    assert {r["run_id"]:r["reason"] for r in excluded}=={"framework":"NON_OPERATIONAL_OR_UNKNOWN","legacy":"UNADMITTED","conflict":"PURPOSE_CONFLICT","stale":"DIGEST_MISMATCH"}
    envelopes=reduce_receipts(accepted)
    assert len(envelopes)==1
    e=envelopes[0]["evidence"]
    assert e["reps"]==2 and e["validated_pass"]==1 and e["validated_fail"]==1
    # Show existing unfiltered behavior, not a second reducer.
    raw=reduce_receipts(rows)
    assert sum(e["evidence"]["reps"] for e in raw)==6
    divergent=copy.deepcopy(operational);divergent["observation"]["success"]=False
    try:
        admit([operational,divergent],manifest)
    except ValueError: duplicate_rejected=True
    else: duplicate_rejected=False
    assert duplicate_rejected
    assert admit(rows,{})[0]==[]
    receipt={"scope":"FRAMEWORK_PROVING_ONLY","admitted_synthetic_controls":len(accepted),"excluded":excluded,"raw_unfiltered_reps":sum(e["evidence"]["reps"] for e in raw),"gated_reps":e["reps"],"gated_pass":e["validated_pass"],"gated_fail":e["validated_fail"],"divergent_duplicate_rejected":duplicate_rejected,"empty_manifest_fails_closed":True,"limitations":"manifest trusted fixture; no production admission authority, signatures, or promotion; operational labeled rows entirely synthetic","status":"PASS"}
    for name,payload in [("receipt.json",receipt),("synthetic-input.json",rows),("synthetic-admission.json",manifest),("gated-reduction.json",envelopes)]:
        (out/name).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("DOE_PURPOSE="+json.dumps(receipt),flush=True)
if __name__=="__main__": main()
