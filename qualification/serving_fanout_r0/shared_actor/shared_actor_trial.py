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

TASKS=("text-repair-v0","api-boundary-classification-v1")
HARNESS_DIGEST="e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83"
HARNESS_REF="ghcr.io/sempersupra/model-spelunker-harness-openworker@sha256:"+HARNESS_DIGEST
ADMISSION_REF="github:SemperSupra/model-spelunker@4f939c4beccb7652b851c4a228d78d804b0e95c7:qualification/harness-artifacts/openworker-5bc10d928e0b-linux-x64.admission-v2.json"

def check_receipt(body,task,exitcode,expected_model):
    if body.get("task",{}).get("id")!=task:
        raise ValueError("task receipt identity mismatch")
    candidate=body.get("candidate",{})
    harness=candidate.get("harness",{})
    model=candidate.get("model",{})
    if harness.get("artifact_ref")!=HARNESS_REF or harness.get("admission_ref")!=ADMISSION_REF:
        raise ValueError("harness provenance mismatch")
    if model.get("id")!=expected_model or model.get("provider")!="ollama":
        raise ValueError("model identity mismatch")
    observation=body.get("observation",{})
    success=observation.get("success")
    if not isinstance(success,bool) or exitcode!=(0 if success else 1):
        raise ValueError("verifier success and process result do not reconcile")
    if not isinstance(body.get("evidence_digest"),str) or not body["evidence_digest"].startswith("sha256:"):
        raise ValueError("missing independent receipt evidence digest")
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

def execute_one(task,mode,block,outdir,venv):
    prefix="%s-block%d-%s"%(mode,block,task)
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
    return {"task":task,"mode":mode,"block":block,"process_exit":proc.returncode,
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
            "design":"2 blocks, reversed order, same pair of independently verified task packages",
            "phases":[]}
    for block in (1,2):
        # Paired comparison has task/context warmness carry-over and sample-size caveats.
        modes=("serial","parallel") if block==1 else ("parallel","serial")
        for mode in modes:
            started=time.monotonic()
            if mode=="serial":
                jobs=[execute_one(t,mode,block,outdir,venv) for t in TASKS]
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                    futures={t:ex.submit(execute_one,t,mode,block,outdir,venv) for t in TASKS}
                    jobs=[futures[t].result() for t in TASKS]
            assert len(set(x["run_id"] for x in jobs))==len(jobs),"duplicate run ids"
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
        print("SHARED_ACTOR mode=%s block=%s wall=%.2f accepted=%d/2"%(p["mode"],p["block"],p["elapsed_wall_seconds"],p["verified_successes"]))
    print("TASK_SUCCESS_NOT_INFERRED_FROM_CI_STATUS")
if __name__=="__main__":
    main()
