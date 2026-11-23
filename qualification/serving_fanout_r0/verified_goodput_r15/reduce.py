#!/usr/bin/env python3
"""R15 independent reducer for existing #139-validated R6/R7 agent task receipts.

Consumes the ORIGINAL 25-file public GitHub Actions ZIP; never executes an agent.
Checks all 24 task v1 receipts against the R6/R7 phase summary, pins full model,
harness, task and source provenance, then computes observed completed-valid
tasks per hour. This does not infer hardware spare capacity or sustained SLOs.
"""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zipfile

MODEL_REF = "ollama-sha256:8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
HARNESS_REF = "ghcr.io/sempersupra/model-spelunker-harness-openworker@sha256:e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83"
ADMISSION_REF = "github:SemperSupra/model-spelunker@4f939c4beccb7652b851c4a228d78d804b0e95c7:qualification/harness-artifacts/openworker-5bc10d928e0b-linux-x64.admission-v2.json"
TASK_DIGEST = "sha256:a51be2ffb8cbe2cacac72f038bb88a1649d491ff853244adb729981c9d6c24cc"
RUN_ID = "45173592480"
SOURCE_SHA = "aa0f0144d266492643390742fe0a628283130400"
ZIP_SHA256 = "0904c7f87f6e6b2abd2f3124eee2e579d08426a6bbe0b768d0a9532b6a74110e"
MODES = {"serial":2,"parallel":2,"two_waves2":4,"burst4":4}
EXPECTED_CELLS = {(block,mode) for block in (1,2) for mode in MODES}

class InvalidEvidence(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise InvalidEvidence(message)

def number(x, what, strictly_positive=True):
    require(type(x) in (int,float) and math.isfinite(x),what+": nonfinite/non-numeric")
    require(x>0 if strictly_positive else x>=0,what+": negative/zero")
    return float(x)

def strict_json(data):
    require(len(data)<=1_048_576,"oversized JSON member")
    try:
        obj=json.loads(data,parse_constant=lambda s: (_ for _ in ()).throw(InvalidEvidence("JSON NaN/Infinity")))
    except (ValueError,TypeError,UnicodeError) as e:
        raise InvalidEvidence("invalid JSON member") from e
    require(isinstance(obj,dict),"JSON object required")
    return obj

def reduce_bytes(data,expected_zip_sha=ZIP_SHA256,expected_run_id=RUN_ID,expected_source_sha=SOURCE_SHA):
    require(type(data) is bytes and 0<len(data)<=4*1024*1024,"invalid ZIP byte length")
    actual=hashlib.sha256(data).hexdigest()
    require(actual==expected_zip_sha,"original artifact ZIP digest drift")
    try:
        archive=zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile,ValueError) as e:
        raise InvalidEvidence("malformed ZIP") from e
    with archive:
        entries=archive.infolist()
        names=[f.filename for f in entries]
        require(len(names)==25 and len(set(names))==25,"unexpected ZIP cardinality or duplicate")
        require("shared-actor-summary.json" in names,"missing source summary")
        require(all(not f.is_dir() and f.file_size<=1_048_576 and f.compress_size<=4*1024*1024
                    and not f.filename.startswith("/") and "/" not in f.filename and "\\" not in f.filename
                    for f in entries),"unsafe ZIP member")
        require(sum(f.file_size for f in entries)<=3*1024*1024,"ZIP extraction size limit exceeded")
        summary=strict_json(archive.read("shared-actor-summary.json"))
        require(summary.get("evidence_class")=="REAL_PUBLIC_CPU_SHARED_SERVER_CONFIGURED_AGENT_SCREEN","wrong source class")
        require(summary.get("backend")=="ollama" and summary.get("model")=="qwen3:1.7b","wrong model or backend")
        require(summary.get("exact_model_artifact")=="UNKNOWN_MAF_BINDING","no invented MAF proof")
        require(summary.get("harness")=="openworker" and summary.get("harness_artifact_ref")==HARNESS_REF,"wrong harness")
        require(summary.get("source_sha")==expected_source_sha and summary.get("run_id")==expected_run_id,"run/source lineage drift")
        require(summary.get("shared_server_parallel_slots")==2 and summary.get("server_localhost_only") is True,"wrong server envelope")
        phases=summary.get("phases")
        require(isinstance(phases,list) and len(phases)==8,"expected exactly eight paired phases")
        seen_cells=set()
        seen_runs=set()
        used_names={"shared-actor-summary.json"}
        result=[]
        for p in phases:
            require(isinstance(p,dict),"bad phase")
            block,mode=p.get("block"),p.get("mode")
            require(type(block) is int and block in (1,2) and mode in MODES,"unsupported phase")
            key=(block,mode)
            require(key not in seen_cells,"duplicate phase")
            seen_cells.add(key)
            elapsed=number(p.get("elapsed_wall_seconds"),"phase wall")
            tasks=p.get("tasks")
            require(isinstance(tasks,list) and len(tasks)==MODES[mode],"incorrect workload size")
            successes=0
            per_task=[]
            used_slots=set()
            for row in tasks:
                require(isinstance(row,dict),"bad summary task")
                slot=row.get("workcell")
                require(slot in ("agentA","agentB","agentC","agentD") and slot not in used_slots,"duplicate/invalid workcell")
                used_slots.add(slot)
                require(row.get("task")=="text-repair-v0" and row.get("mode")==mode and row.get("block")==block,"workload mismatch")
                name="%s-block%d-%s-task.json"%(mode,block,slot)
                require(name in names and name not in used_names,"missing or reused independently validated receipt")
                used_names.add(name)
                raw=strict_json(archive.read(name))
                require(raw.get("schema_version")==1,"not original v1 receipt")
                task=raw.get("task")
                require(isinstance(task,dict) and task.get("id")=="text-repair-v0" and
                        task.get("task_class")=="software.bounded-repair" and
                        task.get("package_digest")==TASK_DIGEST and
                        task.get("source_commit")==expected_source_sha,"task package/source drift")
                candidate=raw.get("candidate",{})
                harness=candidate.get("harness",{})
                model=candidate.get("model",{})
                require(harness.get("artifact_ref")==HARNESS_REF and harness.get("admission_ref")==ADMISSION_REF,"candidate harness drift")
                require(model.get("provider")=="ollama" and model.get("id")=="qwen3:1.7b" and
                        model.get("artifact_ref")==MODEL_REF,"candidate model representation drift")
                rid=raw.get("run_id")
                require(type(rid) is str and rid and rid not in seen_runs and rid==row.get("run_id"),"task run duplicate/mismatch")
                seen_runs.add(rid)
                digest=raw.get("evidence_digest")
                require(type(digest) is str and re.fullmatch(r"sha256:[0-9a-f]{64}",digest) and
                        digest==row.get("evidence_digest"),"evidence digest mismatch")
                obs=raw.get("observation",{})
                success=obs.get("success")
                require(type(success) is bool and success is row.get("verified_task_success"),"independent validator mismatch")
                require(obs.get("termination_class")==row.get("termination_class"),"termination-class mismatch")
                wall=number(obs.get("wall_seconds"),"task wall")
                client_wall=number(row.get("client_wall_seconds"),"client wall")
                require(abs(wall-number(row.get("task_wall_seconds"),"summary wall"))<=.000005,
                        "task wall time discrepancy")
                require(wall<=client_wall+1,"task wall exceeds client wall")
                require(client_wall<=elapsed+2,"task outside enclosing phase")
                require(obs.get("tool_calls")==row.get("tool_calls"),"tool-count discrepancy")
                require(obs.get("verifier_exit_code")==row.get("verifier_exit_code"),"verifier status discrepancy")
                if success:
                    require(obs.get("termination_class")=="semantic-success" and
                            obs.get("verifier_exit_code")==0 and
                            obs.get("candidate_exit_code")==0 and
                            obs.get("timed_out") is False and
                            obs.get("state_changed") is True and row.get("process_exit")==0,
                            "not independently verified successful task")
                    successes+=1
                else:
                    require(obs.get("termination_class")!="semantic-success" and
                            row.get("process_exit")!=0,"failed task mislabeled successful")
                per_task.append(wall)
            require(type(p.get("verified_successes")) is int and p["verified_successes"]==successes,
                    "reported phase success count mismatch")
            result.append({
                "block":block,"policy":mode,"task_class":"software.bounded-repair",
                "valid_task_receipts":len(tasks),"verified_successes":successes,
                "observed_phase_wall_seconds":round(elapsed,6),
                "observed_verified_tasks_per_hour":round(3600*successes/elapsed,3),
                "observed_request_task_wall_p95_seconds":round(sorted(per_task)[math.ceil(.95*len(per_task))-1],6),
                "confidence":"EXPLORATORY_TWO_OR_FOUR_IDENTICAL_TASKS_PER_PHASE",
            })
        require(seen_cells==EXPECTED_CELLS,"missing phase")
        require(used_names==set(names),"extra ZIP receipt members")
        paired=[]
        for block in (1,2):
            records={r["policy"]:r for r in result if r["block"]==block}
            for baseline,candidate in (("serial","parallel"),("two_waves2","burst4")):
                a,b=records[baseline],records[candidate]
                require(a["valid_task_receipts"]==b["valid_task_receipts"],"unmatched paired task cardinality")
                av=a["observed_verified_tasks_per_hour"]
                bv=b["observed_verified_tasks_per_hour"]
                paired.append({"block":block,"baseline":baseline,"candidate":candidate,
                               "observed_goodput_ratio":round(bv/av,4) if av>0 else None,
                               "ratio_status":"OBSERVED_DESCRIPTIVE_ONLY" if av>0 else "UNKNOWN_ZERO_VERIFIED_BASELINE"})
        return {
            "schema":"serving-validated-goodput-r15/v1",
            "evidence_class":"INDEPENDENT_VERIFIER_CROSSCHECK_OF_REAL_PUBLIC_CPU_AGENT_RECEIPTS",
            "original_artifact_zip_sha256":actual,
            "github_run_id":expected_run_id,"source_sha":expected_source_sha,
            "qualified_harness_artifact":HARNESS_REF,"model_runtime_digest":MODEL_REF,
            "task_package_digest":TASK_DIGEST,
            "total_validated_task_receipts":len(seen_runs),
            "total_independently_verified_successes":sum(x["verified_successes"] for x in result),
            "cells":sorted(result,key=lambda x:(x["block"],x["policy"])),
            "paired_comparisons":paired,
            "observed_resource_reserve":None,
            "resource_reserve_reason":"ORIGINAL_R6_R7_TASK_RECEIPTS_HAVE_NO_SAME_PHASE_PHYSICAL_UTILIZATION_SAMPLES",
            "prefill_decode_join":None,
            "prefill_decode_join_reason":"R13_TIMINGS_FROM_DIFFERENT_RUN_SUBSTRATE_AND_PROMPT_CONFIG_NOT_A_VALID_JOIN",
            "confidence":"TWO_ORDER_REVERSED_BLOCKS_NOT_POPULATION_GENERALIZATION",
            "promotion":"HOLD_TASK_CLASS_LIMITED_NO_RESERVE_OR_SUSTAINED_SLO",
        }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--artifact",required=True)
    parser.add_argument("--out",required=True)
    parser.add_argument("--expected-zip-sha256",default=ZIP_SHA256)
    args=parser.parse_args()
    try:
        reduced=reduce_bytes(Path(args.artifact).read_bytes(),expected_zip_sha=args.expected_zip_sha256)
        Path(args.out).write_text(json.dumps(reduced,indent=2,sort_keys=True)+"\n")
        for cell in reduced["cells"]:
            print("R15 block=%s mode=%s success=%s/%s observed_goodput_tph=%s"%
                  (cell["block"],cell["policy"],cell["verified_successes"],
                   cell["valid_task_receipts"],cell["observed_verified_tasks_per_hour"]))
        print("R15_INDEPENDENT_TASK_RECEIPTS_VERIFIED=24 RESERVE=UNKNOWN PROMOTION=HOLD")
    except (OSError,InvalidEvidence,zipfile.BadZipFile) as exc:
        parser.exit(2,"R15_REJECTED: %s\n"%exc)

if __name__=="__main__":
    main()
