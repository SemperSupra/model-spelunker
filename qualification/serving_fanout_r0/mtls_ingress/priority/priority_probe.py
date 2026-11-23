#!/usr/bin/env python3
"""R15: existing nginx mTLS class quota versus no-reservation baseline, public CPU."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import random
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mtls_probe as auth

VERSIONS={"baseline":"https://127.0.0.1:18444",
          "reserved":"https://127.0.0.1:18445"}
MODELS={"model":"qwen3:1.7b","digest":auth.EXPECTED_DIGEST}

def prompt(kind):
    if kind=="interactive":
        return "Synthetic short interactive request: explain the first eight steps of incident triage."
    if kind=="batch":
        return ("Synthetic public batch workload. "+
                "List and explain fourteen independent reliability checks with detailed examples. ")*8
    raise ValueError("unknown workload class")

def stream(client,target,kind,job_id,begin,gate=None):
    if kind not in ("interactive","batch"):raise ValueError("wrong class")
    # Caller-controlled X-Class conflicts with the real client certificate role.
    spoof="interactive" if kind=="batch" else "batch"
    payload={"model":"qwen3:1.7b","prompt":prompt(kind),"stream":True,"think":False,
      "keep_alive":"10m","options":{"num_ctx":2048,
        "num_predict":8 if kind=="interactive" else 64,"temperature":0}}
    request=urllib.request.Request(target+"/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json","X-Class":spoof,"X-Tenant":"spoofed"})
    if gate is not None:
        try:gate.wait(timeout=10)
        except threading.BrokenBarrierError as exc:raise RuntimeError("batch arrivals not synchronized") from exc
    started=time.monotonic()
    first=None;finished=None;outputs=0;inputs=0
    try:
        with client.open(request,timeout=145) as response:
            code=response.status
            for line in response:
                if len(line)>1<<20:raise RuntimeError("oversized streaming response")
                event=json.loads(line)
                if event.get("response") and first is None:first=time.monotonic()-started
                if event.get("done"):
                    if finished is not None:raise RuntimeError("duplicate completion")
                    finished=time.monotonic()
                    outputs=int(event.get("eval_count",0))
                    inputs=int(event.get("prompt_eval_count",0))
            if code==200 and (first is None or finished is None or outputs<=0 or inputs<=0):
                raise RuntimeError("accepted response without full streaming model accounting")
    except urllib.error.HTTPError as err:
        if err.code!=503:raise RuntimeError("unexpected HTTP %d"%err.code) from err
        code=503;finished=time.monotonic()
    if code not in (200,503) or finished is None:raise RuntimeError("unknown terminal status")
    return {"job":job_id,"class":kind,"http_status":code,
       "offered_offset_ms":round((started-begin)*1000,3),
       "finished_offset_ms":round((finished-begin)*1000,3),
       "ttft_ms":None if first is None else round(first*1000,3),
       "prompt_tokens":inputs,"output_tokens":outputs,
       "deliberately_spoofed_untrusted_x_class":spoof}

def trial(mode,clients):
    if mode not in VERSIONS:raise ValueError("invalid condition")
    target=VERSIONS[mode];started=time.monotonic()
    batch_gate=threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=3) as pool:
        b1=pool.submit(stream,clients["beta"],target,"batch","batch-1",started,batch_gate)
        b2=pool.submit(stream,clients["beta"],target,"batch","batch-2",started,batch_gate)
        time.sleep(.15)
        interactive=pool.submit(stream,clients["alpha"],target,"interactive","interactive",started)
        rows=[b1.result(),b2.result(),interactive.result()]
    rows.sort(key=lambda r:r["job"])
    return {"mode":mode,"wall_ms":round((time.monotonic()-started)*1000,3),
            "observations":rows}

def validate_pair(a,b):
    if {a["mode"],b["mode"]}!={"baseline","reserved"}:
        raise ValueError("different policies required")
    for result in (a,b):
        rows=result["observations"]
        if sorted(x["job"] for x in rows)!=["batch-1","batch-2","interactive"]:
            raise ValueError("missing/duplicate mixed job")
        for row in rows:
            if row["http_status"] not in (200,503):raise ValueError("unknown HTTP result")
            if row["finished_offset_ms"]<=row["offered_offset_ms"]:
                raise ValueError("clock inversion")
        interactive=next(x for x in rows if x["job"]=="interactive")
        started_batches=[x for x in rows if x["class"]=="batch"]
        if max(x["offered_offset_ms"] for x in started_batches)>=interactive["offered_offset_ms"]:
            raise ValueError("interactive did not arrive after both batch offers")
        accepted_batch=[x for x in started_batches if x["http_status"]==200]
        if not accepted_batch or min(x["finished_offset_ms"] for x in accepted_batch)<=interactive["offered_offset_ms"]:
            raise ValueError("no overlapping batch request when interactive arrives")
    if next(x for x in a["observations"] if x["job"]=="interactive")["http_status"]==200 and \
       next(x for x in b["observations"] if x["job"]=="interactive")["http_status"]==503:
        return "INVERTED_BENEFIT"
    baseline=a if a["mode"]=="baseline" else b
    reserved=b if b["mode"]=="reserved" else a
    base_rows=baseline["observations"];res_rows=reserved["observations"]
    if any(x["http_status"]==200 and x["output_tokens"]<=0 for x in base_rows+res_rows):
        raise ValueError("false model success")
    # One synthetic confirmed batch generation is identical between treatments.
    base_tokens=[x["prompt_tokens"] for x in base_rows if x["class"]=="batch" and x["http_status"]==200]
    res_tokens=[x["prompt_tokens"] for x in res_rows if x["class"]=="batch" and x["http_status"]==200]
    if not base_tokens or not res_tokens or len(set(base_tokens+res_tokens))!=1:
        raise ValueError("batch prompt token count drift")
    base_ok=sorted(x["http_status"] for x in base_rows)
    reserved_ok=sorted(x["http_status"] for x in res_rows)
    if base_ok==[200,200,503] and reserved_ok==[200,200,503]:
        base_interactive=next(x for x in base_rows if x["job"]=="interactive")
        res_interactive=next(x for x in res_rows if x["job"]=="interactive")
        if base_interactive["http_status"]==503 and res_interactive["http_status"]==200 and \
          sum(x["http_status"]==200 for x in res_rows if x["class"]=="batch")==1:
            return "CERT_BOUND_INTERACTIVE_ADMISSION_SCREEN_PASS"
    return "INCONCLUSIVE_OR_PRIORITY_ADMISSION_NOT_DEMONSTRATED"

def experiment(cert_dir):
    directory=Path(cert_dir)
    ca=directory/"ca.crt"
    clients={name:auth.tls_opener(ca,directory/(name+".crt"),directory/(name+".key"))
             for name in ("alpha","beta","gamma")}
    negatives={
       "unmapped_trusted_cert":auth.auth_rejection(VERSIONS["reserved"],clients["gamma"]),
       "no_client_cert":auth.auth_rejection(VERSIONS["reserved"],auth.tls_opener(ca)),
       "wrong_ca":auth.auth_rejection(VERSIONS["reserved"],auth.tls_opener(ca,directory/"rogue.crt",directory/"rogue.key")),
    }
    rng=random.Random(31615)
    pairs=[]
    for rep in (1,2,3):
        policies=["baseline","reserved"]
        rng.shuffle(policies)
        observed={mode:trial(mode,clients) for mode in policies}
        verdict=validate_pair(observed["baseline"],observed["reserved"])
        pairs.append({"replicate":rep,"order":policies,"result":verdict,"baseline":observed["baseline"],
            "reserved":observed["reserved"]})
    if negatives["unmapped_trusted_cert"].get("status")!=403:
        raise ValueError("valid cert without authorized role did not fail with HTTP 403")
    if not all(x.get("denied") for x in negatives.values()):
        raise ValueError("unauthorized credential accepted")
    return {"evidence_class":"PUBLIC_CPU_REAL_CERT_BOUND_CLASS_RESERVATION_EXPLORATORY",
       "run_id":os.getenv("GITHUB_RUN_ID","UNKNOWN"),
       "source_sha":os.getenv("GITHUB_SHA","UNKNOWN"),
       "model_runtime_digest":auth.EXPECTED_DIGEST,
       "nginx_baseline_global":2,"nginx_reserved_global":2,
       "nginx_reserved_batch_max":1,
       "certificate_role_mapping":"EPHEMERAL_SYNTHETIC_CA_SUBJECT_ONLY",
       "untrusted_header_used_for_role":False,
       "negative_auth":negatives,"pairs":pairs,
       "interactive_priority": "ADMISSION_ONLY_NO_GPU_PREEMPTION_OR_P95_GUARANTEE",
       "tenant_governance":"NOT_QUALIFIED",
       "production_admission":"NO_PROMOTION"}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cert-dir",required=True,type=Path)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    result=experiment(args.cert_dir)
    blob=json.dumps(result,sort_keys=True,indent=2)+"\n"
    args.out.write_text(blob)
    for pair in result["pairs"]:
        print("R15_REP=%d R15_TREATMENT=%s"% (pair["replicate"],pair["result"]))
        for name in ("baseline","reserved"):
            rows=pair[name]["observations"]
            print("R15_REP=%d mode=%s statuses=%s"%(pair["replicate"],name,
                  [(r["job"],r["http_status"]) for r in rows]))
    print("R15_RESULT_SHA256="+hashlib.sha256(blob.encode()).hexdigest())
if __name__=="__main__":
    main()
