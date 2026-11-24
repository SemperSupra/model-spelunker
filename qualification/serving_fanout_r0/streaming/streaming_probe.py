#!/usr/bin/env python3
"""Public-loopback Ollama streaming timing probe. Direct model only; no agent validation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import platform
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MODEL = "qwen3:1.7b"
PIN = "8f68893c685c"
VOCAB = "amber cedar solid orbit pixel lunar river delta field vector signal cobalt".split()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None

def origin(raw):
    p = urllib.parse.urlsplit(raw)
    if p.scheme != "http" or p.username or p.password or p.path or p.query or p.fragment:
        raise ValueError("invalid origin")
    if p.hostname not in ("localhost", "127.0.0.1", "::1") or not p.port:
        raise ValueError("non-loopback or missing explicit port")
    return p.geturl().rstrip("/")

def opener():
    return urllib.request.build_opener(NoRedirect())

def read_json(client, url, body=None, timeout=30):
    headers = {"Content-Type":"application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with client.open(req,timeout=timeout) as r:
        if r.status != 200:
            raise ValueError("non-200 response")
        return json.loads(r.read(1048576))

def digest(client, base, model=MODEL, prefix=PIN):
    for item in read_json(client,base+"/api/tags").get("models",[]):
        if item.get("name")==model:
            value=item.get("digest","").removeprefix("sha256:")
            if len(value)!=64 or not all(c in "0123456789abcdef" for c in value) or not value.startswith(prefix):
                raise ValueError("model representation digest drift")
            return value
    raise ValueError("model absent")

def prompt(index, cohort, kind):
    if kind not in ("shared","distinct"):
        raise ValueError("unknown prefix type")
    words=[]
    for _ in range(16):
        words.extend(VOCAB if kind=="shared" else VOCAB[index:]+VOCAB[:index])
    return "Synthetic cohort %08d. %s Instruction %02d: Describe a reliable software test in one short sentence." % (
        cohort," ".join(words),index)

def stream_one(client,base,model,cohort,index,kind,*,prompt_text=None,response_sink=None,strict_phases=False):
    request={
        "model":model,"prompt":prompt(index,cohort,kind) if prompt_text is None else prompt_text,"stream":True,"think":False,
        "keep_alive":"10m","options":{"num_ctx":2048,"num_predict":12,"temperature":0},
    }
    payload=json.dumps(request).encode()
    started=time.monotonic_ns()
    req=urllib.request.Request(base+"/api/generate",data=payload,headers={"Content-Type":"application/json"})
    first=None
    done=None
    with client.open(req,timeout=90) as response:
        if response.status!=200:raise ValueError("HTTP error")
        for line in response:
            if len(line)>1048576:raise ValueError("oversized stream chunk")
            chunk=json.loads(line)
            if response_sink is not None and isinstance(chunk.get("response"),str):
                response_sink(chunk["response"])
            if chunk.get("response") and first is None:
                first=(time.monotonic_ns()-started)/1e6
            if chunk.get("done"):
                if done is not None: raise ValueError("duplicate done")
                done=(chunk,(time.monotonic_ns()-started)/1e6)
    if first is None or done is None or first<=0 or first>done[1]:
        raise ValueError("no first token or completion")
    data,elapsed=done
    if data.get("eval_count",0)<1 or data.get("prompt_eval_count",0)<1:
        raise ValueError("no server token counts")
    if strict_phases:
        for key in ("prompt_eval_count","eval_count","prompt_eval_duration","eval_duration","load_duration"):
            if type(data.get(key)) is not int or data[key]<0:
                raise ValueError("missing or invalid native counter "+key)
    return {"index":index,"ttft_ms":first,"elapsed_ms":elapsed,
            "prompt_tokens":data["prompt_eval_count"],"output_tokens":data["eval_count"],
            "prefill_ms":data.get("prompt_eval_duration",0)/1e6,
            "decode_ms":data.get("eval_duration",0)/1e6,
            "load_ms":data.get("load_duration",0)/1e6}

def condition(client,base,model,rep,concurrent,kind,cohort):
    if concurrent not in (1,2,4) or rep not in (1,2) or kind not in ("shared","distinct"):
        raise ValueError("invalid treatment")
    started=time.monotonic_ns()
    if concurrent==1:
        results=[stream_one(client,base,model,cohort,i,kind) for i in range(4)]
    else:
        with ThreadPoolExecutor(max_workers=concurrent) as pool:
            results=list(pool.map(lambda i:stream_one(client,base,model,cohort,i,kind),range(4)))
    return {"replicate":rep,"client_concurrency":concurrent,"prefix_kind":kind,"cohort":cohort,
            "wall_ms":(time.monotonic_ns()-started)/1e6,"samples":results}

def value(path):
    try:return Path(path).read_text().strip()
    except OSError:return "UNKNOWN"

def fingerprint():
    cpu = next((line.split(":",1)[1].strip() for line in value("/proc/cpuinfo").splitlines() if line.startswith("model name")), "UNKNOWN")
    mem = next((line.split(":",1)[1].strip() for line in value("/proc/meminfo").splitlines() if line.startswith("MemTotal:")), "UNKNOWN")
    return {"os":platform.system(),"machine":platform.machine(),"cpu_model":cpu,
        "visible_cpus":os.cpu_count(),"memory_total":mem,
        "cgroup_cpu_max":value("/sys/fs/cgroup/cpu.max"),
        "cgroup_cpuset":value("/sys/fs/cgroup/cpuset.cpus.effective"),
        "runner_image":os.environ.get("ImageOS","UNKNOWN")}

def run(base,model=MODEL,prefix=PIN):
    base=origin(base)
    client=opener()
    model_id=digest(client,base,model,prefix)
    stream_one(client,base,model,8876,99,"shared") # unmeasured warm-up
    specs=[(n,k) for n in (1,2,4) for k in ("shared","distinct")]
    rng=random.Random(3165)
    report={"evidence_class":"REAL_PUBLIC_CPU_STREAMING_DIRECT_INFERENCE_EXPLORATORY",
        "model":model,"runtime_model_digest":model_id,
        "foundry_identity":"UNKNOWN","agent_task_validity":"NOT_TESTED",
        "kv_cache_hit_rate":"NOT_OBSERVED","streaming_ttft":"MEASURED_ON_PUBLIC_CPU",
        "source_sha":os.environ.get("GITHUB_SHA","UNKNOWN"),
        "run_id":os.environ.get("GITHUB_RUN_ID","UNKNOWN"),
        "backend_version":os.environ.get("OLLAMA_VERSION","UNKNOWN"),
        "host":fingerprint(),"conditions":[]}
    for rep in (1,2):
        rng.shuffle(specs)
        for n,kind in specs:
            cohort=3165000+rep*100+n*10+(kind=="distinct")
            report["conditions"].append(condition(client,base,model,rep,n,kind,cohort))
    return report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--base",default="http://127.0.0.1:11434")
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    result=run(args.base)
    payload=json.dumps(result,indent=2,sort_keys=True)+"\n"
    Path(args.out).write_text(payload)
    print("STREAMING_PUBLIC_CPU_RECEIPT_SHA256="+hashlib.sha256(payload.encode()).hexdigest())
    print("STREAMING_CELLS="+str(len(result["conditions"])))
if __name__=="__main__":
    main()
