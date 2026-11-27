"""Compose existing exact-source purpose and resource gates with unique-work receipts.
Framework proof only: caller manifest is deliberately overbroad and not authority.
No new production reducer, scheduler, or evidence schema.
"""
import copy
import importlib.util
import json
import math
import pathlib
import subprocess
import sys

import prove as unique

PURPOSE_HEAD="e01282cef01c77bb685bf4062f453b9e1cdca998"
RESOURCE_HEAD="355195c5ca90673665b32736e7ab70973b2ca531"

def load(name,root,head,relative):
    actual=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
    unique.require(actual==head,"peer source drift")
    spec=importlib.util.spec_from_file_location(name,root/relative)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

def metric(value,unit,source):
    return {"value":value,"unit":unit,"source":source,"status":"OBSERVED" if value is not None else "UNKNOWN"}

def row_for(attempt,raw,commit):
    r=json.loads(raw)
    return {"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","run_id":attempt["run_id"],
        "receipt_sha256":unique.sha(raw),"source_commit":commit,"accepted":r["observation"]["success"],
        "assignment":attempt["assignment"],"attempt":attempt["attempt"],
        "metrics":{"cpu_seconds":metric(attempt["waited_child_cpu_seconds"],"cpu-s",attempt["cpu_scope"]),
                   "wall_seconds":metric(attempt["wall_seconds"],"s","wrapper monotonic"),
                   "gpu_seconds":metric(None,"gpu-s","not instrumented"),"energy_joules":metric(None,"J","not instrumented"),
                   "human_attention_seconds":metric(None,"s","not instrumented")}}

def combine(attempts,raws,measurements,commit,elapsed,resource_gate):
    # The original reducer checks the fixed plan, source/config/experiment,
    # receipts, terminal outcomes and unique assignment accounting.
    summary=unique.reduce(attempts,raws,elapsed,commit)
    unique.require(len(measurements)==len(attempts),"incomplete measurement set")
    by_id={}
    for m in measurements:
        rid=m["run_id"];unique.require(rid not in by_id,"duplicate measurement");by_id[rid]=m
    for attempt,raw in zip(attempts,raws):
        unique.require(attempt["run_id"] in by_id,"missing measurement")
        m=by_id[attempt["run_id"]]
        # Require exact scope/source/value equality to observed attempt record.
        # Neither record is cryptographic producer attestation.
        unique.require(m==row_for(attempt,raw,commit),"measurement/attempt mismatch")
        resource_gate.validate(m,raw)
    costs={}
    for field in ("cpu_seconds","wall_seconds","gpu_seconds","energy_joules","human_attention_seconds"):
        vals=[m["metrics"][field]["value"] for m in measurements]
        known=all(unique.number(v) for v in vals)
        total=sum(vals) if known else None
        n=summary["accepted_unique"]
        costs[field]={"status":"OBSERVED" if known else "UNKNOWN","all_attempt_total":total,
            "per_unique_accepted":total/n if n and total is not None else None}
    return summary,costs

def main(evidence,purpose_root,resource_root,out):
    out.mkdir(parents=True,exist_ok=False)
    purpose=load("peer_purpose",purpose_root,PURPOSE_HEAD,"qualification/actor_doe_evidence_r0/prove.py")
    resource_gate=load("peer_resource",resource_root,RESOURCE_HEAD,"qualification/resource_join_r0/prove.py")
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=unique.ROOT,text=True).strip()
    attempts=json.loads((evidence/"attempts.json").read_text())
    original=json.loads((evidence/"summary.json").read_text())
    raws=[(evidence/str(i)/"receipt.json").read_bytes() for i in range(len(attempts))]
    rows=[json.loads(raw) for raw in raws]
    measurements=[row_for(a,r,commit) for a,r in zip(attempts,raws)]
    elapsed=original["campaign_elapsed_seconds"]
    summary,costs=combine(attempts,raws,measurements,commit,elapsed,resource_gate)
    for key in ("assigned","attempts","accepted_unique","accepted_attempts","first_pass_unique","not_started"):
        unique.require(summary[key]==original[key],"original accounting regression")
    unique.require(costs["cpu_seconds"]["status"]=="OBSERVED" and costs["cpu_seconds"]["all_attempt_total"]>0,"expected Linux CPU observations")
    unique.require(costs["cpu_seconds"]["per_unique_accepted"]==costs["cpu_seconds"]["all_attempt_total"]/2,"unique denominator")
    unique.require(costs["energy_joules"]["all_attempt_total"] is None,"invented energy")
    # Reuse the exact existing purpose gate even with a caller manifest
    # claiming each actual framework-proving receipt is operational.
    manifest={r["run_id"]:{"receipt_digest":purpose.digest(r),"purpose":"OPERATIONAL_QUALIFICATION"} for r in rows}
    eligible,excluded=purpose.admit(rows,manifest)
    unique.require(not eligible and len(excluded)==len(rows) and all(x["reason"]=="PURPOSE_CONFLICT" for x in excluded),"framework evidence escaped")
    unique.require(purpose.reduce_receipts(eligible)==[] and purpose.admit(rows,{})[0]==[],"unexpected operational envelope")
    negatives=[]
    for field,value in (("receipt_sha256","wrong"),("run_id","wrong"),("source_commit","0"*40),("accepted",not measurements[0]["accepted"])):
        bad=copy.deepcopy(measurements);bad[0][field]=value;negatives.append(bad)
    bad=copy.deepcopy(measurements);bad[0]["metrics"]["energy_joules"]["value"]=0;negatives.append(bad)
    bad=copy.deepcopy(measurements);bad[0]["metrics"]["cpu_seconds"]["value"]=float("nan");negatives.append(bad)
    bad=copy.deepcopy(measurements);bad[0]["metrics"]["cpu_seconds"]["source"]="other accounting scope";negatives.append(bad)
    negatives.extend([measurements[:-1],measurements[:-1]+[measurements[0]]])
    for bad in negatives:
        try:combine(attempts,raws,bad,commit,elapsed,resource_gate)
        except ValueError:continue
        raise RuntimeError("planted measurement fault accepted")
    result={"scope":"FRAMEWORK_PROVING_ONLY","source_commit":commit,
            "peer_sources":{"purpose":PURPOSE_HEAD,"resource":RESOURCE_HEAD},"actual_receipts_reused":len(rows),
            "accepted_unique":summary["accepted_unique"],"accepted_attempts":summary["accepted_attempts"],
            "failed_attempts":summary["failed_attempts"],"costs":costs,"purpose_conflicts":len(excluded),
            "negative_measurement_controls_rejected":len(negatives),"operational_envelopes":[],"promotion_authorized":False,
            "limitations":"Same five serial synthetic attempts reused, no extra inference. CPU waited child accounting excludes cloud provisioning, remote/server CPU and observer overhead. Exact source/digest consistency, not authenticated authority. No production reducer or cross-platform claim."}
    unique.write(out/"measurement-rows.json",measurements);unique.write(out/"summary.json",result)
    print("COMPOSITION="+json.dumps(result,sort_keys=True),flush=True)
if __name__=="__main__":
    main(*(pathlib.Path(x).resolve() for x in sys.argv[1:]))
