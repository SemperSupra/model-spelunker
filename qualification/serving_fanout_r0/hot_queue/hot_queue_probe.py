#!/usr/bin/env python3
"""Bounded live hot-model queue limit falsification; public loopback Ollama only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"streaming"))
import streaming_probe as base

REQUESTS=6
PARALLEL=1
MAX_QUEUE=1
WORDS="amber cobalt cedar lunar river vector field pixel orbit datum signal maple".split()

def one_request(target,model,index,gate,origin):
    handler=base.opener() # each worker has independent HTTP state
    prompt=("Synthetic queue probe cohort %08d, request %02d. "%(31610000,index) +
             (" ".join(WORDS)+" ")*35 + " Write a detailed numbered reliability review of twelve design options.")
    payload={"model":model,"prompt":prompt,"stream":True,"think":False,
             "keep_alive":"10m","options":{"num_ctx":2048,"num_predict":64,"temperature":0}}
    body=json.dumps(payload).encode()
    req=urllib.request.Request(target+"/api/generate",data=body,headers={"Content-Type":"application/json"})
    try:
        gate.wait(timeout=10)
    except threading.BrokenBarrierError as err:
        raise RuntimeError("unable to synchronize offered requests") from err
    start=time.monotonic()
    status=None;finished=None;output=0;prefill=None;first=None
    try:
        with handler.open(req,timeout=170) as response:
            status=response.status
            for line in response:
                if len(line)>1<<20:raise RuntimeError("oversized stream")
                chunk=json.loads(line)
                if first is None and chunk.get("response"):
                    first=time.monotonic()-start
                if chunk.get("done"):
                    finished=time.monotonic()
                    output=chunk.get("eval_count",0)
                    prefill=chunk.get("prompt_eval_count",0)
            if status==200 and (finished is None or output<=0 or prefill<=0):
                raise RuntimeError("successful inference lacked final accounting")
    except urllib.error.HTTPError as exc:
        status=exc.code
        if status not in (503,429):
            raise RuntimeError("unexpected backend HTTP status %s"%status) from exc
        finished=time.monotonic()
    return {"request_index":index,"http_status":status,
            "offered_offset_ms":round((start-origin)*1000,3),
            "finished_offset_ms":round((finished-origin)*1000,3),
            "ttft_ms":None if first is None else round(first*1000,3),
            "output_tokens":output,"input_tokens":prefill}

def classify(rows):
    if len(rows)!=REQUESTS or len({r["request_index"] for r in rows})!=REQUESTS:
        raise ValueError("incomplete or duplicate request receipts")
    if any(r["http_status"] not in (200,429,503) for r in rows):
        return "UNEXPECTED_HTTP_RESULT"
    starts=[r["offered_offset_ms"] for r in rows]
    skew=max(starts)-min(starts)
    finished=min(r["finished_offset_ms"] for r in rows)
    if skew>500 or finished<=max(starts):
        return "INCONCLUSIVE_ARRIVAL_OVERLAP"
    accepted=sum(r["http_status"]==200 for r in rows)
    rejected=sum(r["http_status"] in (429,503) for r in rows)
    if accepted>PARALLEL+MAX_QUEUE:
        return "EXCESS_REQUESTS_COMPLETED_OUTSIDE_GLOBAL_1_PLUS_1_BOUND"
    if rejected>=REQUESTS-(PARALLEL+MAX_QUEUE) and accepted<=PARALLEL+MAX_QUEUE:
        return "GLOBAL_BOUND_COMPATIBLE_FOR_THIS_TRIAL"
    return "INCONCLUSIVE"

def run(target,model="qwen3:1.7b"):
    target=base.origin(target)
    verified_model=base.digest(base.opener(),target,model,"8f68893c685c")
    # Hot model already loaded, so any admission must govern loaded-runner path.
    base.stream_one(base.opener(),target,model,316100,99,"shared")
    gate=threading.Barrier(REQUESTS)
    started=time.monotonic()
    with ThreadPoolExecutor(max_workers=REQUESTS) as pool:
        futures=[pool.submit(one_request,target,model,i,gate,started) for i in range(REQUESTS)]
        observations=[f.result() for f in futures]
    observations.sort(key=lambda item:item["request_index"])
    return {
      "evidence_class":"REAL_PUBLIC_CPU_HOT_LOADED_OLLAMA_QUEUE_LIMIT_EXPLORATORY",
      "source_sha":os.getenv("GITHUB_SHA","UNKNOWN"),
      "run_id":os.getenv("GITHUB_RUN_ID","UNKNOWN"),
      "host":base.fingerprint(),
      "backend_version":os.getenv("OLLAMA_VERSION","UNKNOWN"),
      "exact_model_digest":verified_model,
      "model_artifact_foundry_admission":"UNKNOWN",
      "expected_parallel":PARALLEL,"configured_max_queue":MAX_QUEUE,
      "source_backend_scheduler_sha":"e31fedc57477b2028192de941396538dbc52f9b7",
      "source_backend_envconfig_sha":"0379a2aec2a9573d542deb840766a93694f63ffe",
      "description":"hot-loaded model, 6 near-simultaneously offered stream requests; no retries",
      "unmanaged_client":"PUBLIC_OFFLINE_SYNTHETIC_PROMPTS_NO_AUTH",
      "overload_result":classify(observations),
      "observations":observations,
      "kv_cache_hit_rate":"NOT_OBSERVED",
      "workflow_task_validity":"NOT_APPLICABLE_DIRECT_INFERENCE",
      "production_decision":"NO_PROMOTION",
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",default="http://127.0.0.1:11434")
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    observation=run(args.base)
    text=json.dumps(observation,sort_keys=True,indent=2)+"\n"
    args.out.write_text(text)
    print("HOT_QUEUE_PROBE="+observation["overload_result"])
    print("HOT_QUEUE_COMPLETED="+str(sum(r["http_status"]==200 for r in observation["observations"])))
    print("HOT_QUEUE_REJECTED="+str(sum(r["http_status"]!=200 for r in observation["observations"])))
    print("HOT_QUEUE_RECEIPT_SHA256="+hashlib.sha256(text.encode()).hexdigest())
if __name__=="__main__":
    main()
