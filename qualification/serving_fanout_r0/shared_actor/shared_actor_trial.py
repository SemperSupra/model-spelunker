#!/usr/bin/env python3
"""Bounded public CPU *shared Ollama* experiment; uses existing configured-agent task runner."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

TASKS=(("agentA","text-repair-v0"),("agentB","text-repair-v0"))
FOUR_TASKS=TASKS+(("agentC","text-repair-v0"),("agentD","text-repair-v0"))
HARNESS_DIGEST="e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83"
HARNESS_REF="ghcr.io/sempersupra/model-spelunker-harness-openworker@sha256:"+HARNESS_DIGEST
PUBLIC_MODEL_ARTIFACT="ollama-sha256:8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
TASK_PACKAGE_DIGEST="sha256:a51be2ffb8cbe2cacac72f038bb88a1649d491ff853244adb729981c9d6c24cc"
ADMISSION_REF="github:SemperSupra/model-spelunker@4f939c4beccb7652b851c4a228d78d804b0e95c7:qualification/harness-artifacts/openworker-5bc10d928e0b-linux-x64.admission-v2.json"

def check_receipt(body,task,exitcode,expected_model):
    if body.get("task",{}).get("id")!=task:
        raise ValueError("task receipt identity mismatch")
    if body.get("task",{}).get("package_digest") != TASK_PACKAGE_DIGEST:
        raise ValueError("source task package digest drift")
    candidate=body.get("candidate",{})
    harness=candidate.get("harness",{})
    model=candidate.get("model",{})
    if harness.get("artifact_ref")!=HARNESS_REF or harness.get("admission_ref")!=ADMISSION_REF:
        raise ValueError("harness provenance mismatch")
    if model.get("id")!=expected_model or model.get("provider")!="ollama" or model.get("artifact_ref")!=PUBLIC_MODEL_ARTIFACT:
        raise ValueError("model identity mismatch")
    observation=body.get("observation",{})
    success=observation.get("success")
    if not isinstance(success,bool) or exitcode!=(0 if success else 1):
        raise ValueError("verifier success and process result do not reconcile")
    evidence=body.get("evidence_digest")
    if not isinstance(evidence,str) or len(evidence)!=71 or not evidence.startswith("sha256:") or any(c not in "0123456789abcdef" for c in evidence[7:]):
        raise ValueError("missing independent receipt evidence digest")
    if success and (observation.get("verifier_exit_code")!=0 or observation.get("candidate_exit_code")!=0 or observation.get("timed_out") is True):
        raise ValueError("self-reported success contradicts independent verifier, actuator or timeout")
    if not isinstance(body.get("run_id"),str) or not body["run_id"]:
        raise ValueError("missing source-bound task run identifier")
    if observation.get("termination_class") not in (
       "semantic-success","semantic-failure","execution-error","timeout-censored","validator-invalid"):
        raise ValueError("unrecognized termination class")
    return {"verified_task_success":success,
        "termination_class":observation["termination_class"],
        "failure_class":observation.get("failure_class"),
        "task_wall_seconds":observation.get("wall_seconds"),
        "evidence_digest":body["evidence_digest"],
        "run_id":body.get("run_id"),
        "verifier_exit_code":observation.get("verifier_exit_code"),
        "tool_calls":observation.get("tool_calls")}

def cmd(task,receipt,diag,venv):
    # Run the existing independently validated harness-neutral task interview, not
    # a new execution engine or semantic verifier.
    root=Path(__file__).resolve().parents[3]
    return [
      sys.executable,str(root/"qualification/run_task.py"),
      "--pass-env","MODEL_SPELUNKER_TOOL_HINT_MODE",
      "--pass-env","MODEL_SPELUNKER_MAX_ITERATIONS",
      "--pass-env","MODEL_SPELUNKER_REASONING_EFFORT",
      "--pass-env","MODEL_SPELUNKER_MODEL",
      "--task-commit",os.environ.get("GITHUB_SHA","UNKNOWN"),
      "--substrate-profile-id","gha-cpu-shared-ollama-r6",
      "--substrate-profile-commit","public-r6-shared-ollama-v1",
      "--diagnostics",str(diag),
      str(root/"qualification/tasks"/task),
      os.environ["CANDIDATE_META"],
      str(receipt),
      "--",str(venv/"bin/python"),
      str(root/"qualification/adapters/openworker_projected.py"),
    ]

def execute_one(slot,task,mode,block,outdir,venv):
    prefix="%s-block%d-%s"%(mode,block,slot)
    receipt=outdir/(prefix+"-task.json")
    diagnostic=outdir/(prefix+"-diagnostics.json")
    started=time.monotonic()
    proc=subprocess.run(cmd(task,receipt,diagnostic,venv),capture_output=True,timeout=140,
        env=os.environ.copy(),check=False)
    wall=time.monotonic()-started
    if not receipt.is_file():
        raise RuntimeError("INFRA_FAILURE missing task receipt: "+prefix+" exit="+str(proc.returncode))
    body=json.loads(receipt.read_text())
    valid=check_receipt(body,task,proc.returncode,os.environ.get("OLLAMA_MODEL_TAG","qwen3:1.7b"))
    # Logs are omitted, not re-exported as model evidence. Raw stdout digest is
    # an external troubleshooting aid for these synthetic public fixtures only.
    return {"task":task,"workcell":slot,"mode":mode,"block":block,"process_exit":proc.returncode,
            "client_wall_seconds":round(wall,6),
            "stdout_sha256":"sha256:"+hashlib.sha256(proc.stdout).hexdigest(),
            "stderr_sha256":"sha256:"+hashlib.sha256(proc.stderr).hexdigest(),
            **valid}

def run(outdir,venv):
    outdir.mkdir(parents=True,exist_ok=True)
    if not venv.joinpath("bin/python").is_file():
        raise ValueError("qualified harness interpreter unavailable")
    report={"evidence_class":"REAL_PUBLIC_CPU_SHARED_SERVER_CONFIGURED_AGENT_SCREEN",
            "backend":"ollama","model":"qwen3:1.7b","exact_model_artifact":"UNKNOWN_MAF_BINDING",
            "harness":"openworker","harness_artifact_ref":HARNESS_REF,
            "source_sha":os.environ.get("GITHUB_SHA","UNKNOWN"),
            "run_id":os.environ.get("GITHUB_RUN_ID","UNKNOWN"),
            "shared_server_parallel_slots":2,
            "server_localhost_only":True,
            "design":"R6 2-agent serial/parallel and R7 4-agent two-waves2/burst4 in two reversed-order blocks; same frozen task in isolated workcells",
            "phases":[]}
    for block in (1,2):
        # Paired comparison has task/context warmness carry-over and sample-size caveats.
        modes=("serial","parallel") if block==1 else ("parallel","serial")
        for mode in modes:
            started=time.monotonic()
            if mode=="serial":
                jobs=[execute_one(slot,t,mode,block,outdir,venv) for slot,t in TASKS]
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                    futures={slot:ex.submit(execute_one,slot,t,mode,block,outdir,venv) for slot,t in TASKS}
                    jobs=[futures[slot].result() for slot,t in TASKS]
            assert len(set(x["run_id"] for x in jobs))==len(jobs),"duplicate run ids"
            report["phases"].append({
                "block":block,"mode":mode,"elapsed_wall_seconds":round(time.monotonic()-started,6),
                "tasks":jobs,"verified_successes":sum(x["verified_task_success"] for x in jobs)
            })
    # R7 physical/server saturation screening. Four real agents share just two
    # Ollama serving slots. Each treatment admits four *identical* tasks.
    for block in (1,2):
        modes=("two_waves2","burst4") if block==1 else ("burst4","two_waves2")
        for mode in modes:
            started=time.monotonic()
            if mode=="two_waves2":
                jobs=[]
                for wave in (FOUR_TASKS[:2],FOUR_TASKS[2:]):
                    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                        futures={slot:ex.submit(execute_one,slot,t,mode,block,outdir,venv)
                                 for slot,t in wave}
                        jobs.extend(futures[slot].result() for slot,t in wave)
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                    futures={slot:ex.submit(execute_one,slot,t,mode,block,outdir,venv)
                             for slot,t in FOUR_TASKS}
                    jobs=[futures[slot].result() for slot,t in FOUR_TASKS]
            assert len(jobs)==4 and len(set(x["run_id"] for x in jobs))==4,"invalid saturated workcell identities"
            report["phases"].append({
                "block":block,"mode":mode,"elapsed_wall_seconds":round(time.monotonic()-started,6),
                "tasks":jobs,"verified_successes":sum(x["verified_task_success"] for x in jobs)
            })
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--outdir",type=Path,required=True)
    p.add_argument("--venv",type=Path,required=True)
    args=p.parse_args()
    r=run(args.outdir,args.venv)
    path=args.outdir/"shared-actor-summary.json"
    path.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
    for p in r["phases"]:
        print("SHARED_ACTOR mode=%s block=%s wall=%.2f accepted=%d/%d"%(p["mode"],p["block"],p["elapsed_wall_seconds"],p["verified_successes"],len(p["tasks"])))
    print("TASK_SUCCESS_NOT_INFERRED_FROM_CI_STATUS")
if __name__=="__main__":
    main()
