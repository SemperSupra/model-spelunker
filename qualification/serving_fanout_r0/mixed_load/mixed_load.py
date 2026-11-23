#!/usr/bin/env python3
"""Public free-tier real CPU mixed-load *client-admission* experiment.

Implements two simple client submission policies; it is NOT a production scheduler,
a GPU preemption mechanism, or an admission/tenant security boundary.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import random
import time
import urllib.request

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "streaming"))
import streaming_probe as base

TWO_SLOT_SERVER = 2
TASKS = ("batch-A", "batch-B", "interactive")
WORDS = "amber cedar solid orbit pixel lunar river delta field vector signal cobalt".split()

def prompt(kind, cohort):
    prefix = "Synthetic cohort %08d. " % cohort
    if kind == "interactive":
        return prefix + "Interactive request: Give one short sentence about a healthy service."
    # Same byte/token shape for both batch jobs and both policies; no user data.
    return prefix + (" ".join(WORDS) + " ") * 100 + "Batch synthesis request: Write a short summary."

def stream_work(client, target, model, label, cohort):
    kind = "interactive" if label=="interactive" else "batch"
    payload = {
      "model":model, "prompt":prompt(kind,cohort), "stream":True, "think":False,
      "keep_alive":"10m",
      "options":{"num_ctx":4096,"num_predict":8 if kind=="interactive" else 48,
                 "temperature":0},
    }
    body=json.dumps(payload).encode()
    req=urllib.request.Request(target+"/api/generate",data=body,
                               headers={"Content-Type":"application/json"})
    origin=time.monotonic_ns()
    got_first=None;got_done=None
    with client.open(req,timeout=120) as response:
        if response.status!=200:raise RuntimeError("non-200 model response")
        for line in response:
            if len(line)>1024*1024:raise RuntimeError("oversized response chunk")
            chunk=json.loads(line)
            if chunk.get("response") and got_first is None:
                got_first=(time.monotonic_ns()-origin)/1e6
            if chunk.get("done"):
                if got_done is not None:raise RuntimeError("duplicate done")
                got_done=(chunk,(time.monotonic_ns()-origin)/1e6)
    if got_first is None or got_done is None:
        raise RuntimeError("no streamed first token or final completion")
    answer,elapsed=got_done
    if int(answer.get("prompt_eval_count") or 0)<1 or int(answer.get("eval_count") or 0)<1:
        raise RuntimeError("missing exact serving token accounting")
    if got_first>elapsed:raise RuntimeError("first-token timestamp after final")
    return {
      "job":label,"kind":kind,"ttft_ms":round(got_first,3),
      "wall_ms":round(elapsed,3),
      "prompt_tokens":answer["prompt_eval_count"],"output_tokens":answer["eval_count"],
      "prefill_ms":round(answer.get("prompt_eval_duration",0)/1e6,3),
      "decode_ms":round(answer.get("eval_duration",0)/1e6,3),
      "load_ms":round(answer.get("load_duration",0)/1e6,3),
    }

def trial(client,target,model,policy,rep,cohort):
    if policy not in ("burst2_then_interactive","soft_reserve1") or rep not in (1,2,3):
        raise ValueError("invalid policy/rep")
    begin=time.monotonic_ns()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        a=pool.submit(stream_work,client,target,model,"batch-A",cohort)
        if policy=="burst2_then_interactive":
            b=pool.submit(stream_work,client,target,model,"batch-B",cohort+1)
        else:
            b=None
        # Fixed, modest delay means the first batch attempt is admitted before the
        # interactive arrival; physical preemption is NOT assumed.
        time.sleep(.20)
        interactive_arrival_ms=(time.monotonic_ns()-begin)/1e6
        interactive=pool.submit(stream_work,client,target,model,"interactive",cohort+2)
        result_i=interactive.result()
        # Soft reservation: batch-B waits for interactive response completion;
        # this is deliberately conservative, not a physical server reservation.
        if b is None:
            b=pool.submit(stream_work,client,target,model,"batch-B",cohort+1)
        results=[a.result(),b.result(),result_i]
    total_ms=(time.monotonic_ns()-begin)/1e6
    return {
      "policy":policy,"replicate":rep,"cohort":cohort,
      "interactive_arrival_offset_ms":round(interactive_arrival_ms,3),
      "wall_ms":round(total_ms,3),
      "interactive_ttft_ms":result_i["ttft_ms"],
      "batch_jobs":2,"interactive_jobs":1,"jobs":results,
    }

def validate_pair(burst,reserved):
    if burst["policy"]!="burst2_then_interactive" or reserved["policy"]!="soft_reserve1":
        raise ValueError("cannot compare different treatment identities")
    for role in ("interactive","batch-A","batch-B"):
        a=next(x for x in burst["jobs"] if x["job"]==role)
        b=next(x for x in reserved["jobs"] if x["job"]==role)
        if abs(a["prompt_tokens"]-b["prompt_tokens"])/max(a["prompt_tokens"],b["prompt_tokens"])>.05:
            raise ValueError("token confound across compared conditions: "+role)
    return True

def experiment(endpoint,model="qwen3:1.7b"):
    endpoint=base.origin(endpoint)
    client=base.opener()
    digest=base.digest(client,endpoint,model,"8f68893c685c")
    # A distinct short warm-up avoids ranking cold model activation as policy effect.
    base.stream_one(client,endpoint,model,999998,99,"shared")
    out={
      "evidence_class":"PUBLIC_CPU_LIVE_MIXED_ADMISSION_EXPLORATORY",
      "runtime_model_digest":digest,"model":model,
      "host":base.fingerprint(),"source_sha":os.getenv("GITHUB_SHA","UNKNOWN"),
      "run_id":os.getenv("GITHUB_RUN_ID","UNKNOWN"),"server_parallel_slots":TWO_SLOT_SERVER,
      "task_semantic_validity":"NOT_TESTED_DIRECT_INFERENCE_ONLY",
      "cache_kv_hit_rate":"NOT_OBSERVED",
      "admission_policy_guarantee":"SOFT_CLIENT_SUBMISSION_ONLY_NOT_PHYSICAL_RESERVATION",
      "design":"3 reversed/shuffled paired blocks; 2 long batch requests + 1 interactive; unique cohort",
      "blocks":[],
    }
    rng=random.Random(3168)
    for rep in (1,2,3):
        order=["burst2_then_interactive","soft_reserve1"]
        rng.shuffle(order)
        cells={}
        for treatment in order:
            label=0 if treatment=="burst2_then_interactive" else 1
            cohort=3168000+rep*100+label*10
            cells[treatment]=trial(client,endpoint,model,treatment,rep,cohort)
        validate_pair(cells["burst2_then_interactive"],cells["soft_reserve1"])
        out["blocks"].append({"replicate":rep,"conditions":[cells[k] for k in order]})
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",default="http://127.0.0.1:11434")
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    report=experiment(args.base)
    blob=json.dumps(report,sort_keys=True,indent=2)+"\n"
    args.out.write_text(blob)
    print("MIXED_REPS="+str(len(report["blocks"])))
    print("MIXED_RECEIPT_SHA256="+hashlib.sha256(blob.encode()).hexdigest())
    for block in report["blocks"]:
        for c in block["conditions"]:
            print("MIXED rep=%d policy=%s interactive_ttft_ms=%.1f wall_ms=%.1f"%
                  (block["replicate"],c["policy"],c["interactive_ttft_ms"],c["wall_ms"]))
if __name__=="__main__":
    main()
