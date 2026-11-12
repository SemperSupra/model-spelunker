#!/usr/bin/env python3
"""Real integration: authenticated Go API -> native ComfyUI -> durable PNGs.

No model downloads, no GPU, and no real generative-model quality claims.
Requires both services on loopback on a disposable public runner.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
from urllib import error,request

def fetch(path, token, payload=None):
    base="http://127.0.0.1:8090"
    data=None if payload is None else json.dumps(payload,sort_keys=True).encode()
    req=request.Request(base+path, data=data,
        headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},
        method="POST" if data is not None else "GET")
    with request.urlopen(req,timeout=10) as r:
        raw=r.read(2_000_001)
        if len(raw)>2_000_000:raise RuntimeError("RESPONSE_TOO_LARGE")
        return r.status,raw,r.headers.get("Content-Type")

def main():
    token=os.environ["CONDITIONING_TEST_TOKEN"]
    if len(token)<32: raise RuntimeError("TOKEN_TOO_SHORT")
    deadline=time.monotonic()+125
    while True:
        try:
            status,raw,_=fetch("/api/v1/capabilities",token)
            if status==200 and not json.loads(raw)["production_generator_admitted"]:break
        except (error.URLError,ConnectionError):
            pass
        if time.monotonic()>=deadline:raise RuntimeError("CONTROLLER_BOOT_TIMEOUT")
        time.sleep(1)
    status,raw,_=fetch("/api/v1/openapi.json",token)
    assert status==200 and json.loads(raw)["openapi"]=="3.1.0"
    packet={"request_id":"cpu-integrated-pair-0001",
            "jobs":[{"workflow":"toy-cnn-v1","seed":71,"variant":"base","size":64},
                    {"workflow":"toy-cnn-v1","seed":71,"variant":"modified","size":64}]}
    code,raw,_=fetch("/api/v1/batches",token,packet)
    accepted=json.loads(raw)
    assert code==202 and accepted["idempotent_replay"] is False
    ids=accepted["job_ids"]
    assert len(ids)==2 and len(set(ids))==2
    code,raw,_=fetch("/api/v1/batches",token,packet)
    duplicate=json.loads(raw)
    assert code==202 and duplicate["idempotent_replay"] is True
    assert duplicate["job_ids"]==ids
    output=[]
    for ident in ids:
        while time.monotonic()<deadline:
            _,raw,_=fetch("/api/v1/jobs/"+ident,token)
            state=json.loads(raw)
            if state["state"]=="COMPLETED":break
            if state["state"].startswith("UNKNOWN") or state["state"].startswith("FAILED"):
                raise RuntimeError("JOB_AMBIGUOUS_OR_FAILED")
            time.sleep(0.5)
        else:raise RuntimeError("JOB_TIMEOUT")
        status,png,kind=fetch("/api/v1/jobs/"+ident+"/image",token)
        assert status==200 and kind.startswith("image/png")
        assert png[:8]==bytes.fromhex("89504e470d0a1a0a")
        assert struct.unpack(">II",png[16:24])==(64,64)
        digest=hashlib.sha256(png).hexdigest()
        assert digest==state["image_sha256"]
        assert state["native_prompt_id"]
        output.append({"variant":state["request"]["variant"],"png_sha256":digest,
                       "bytes":len(png),"job_id":ident})
    assert len({x["png_sha256"] for x in output})==2
    print(json.dumps({"schema":"conditioning-controller-native-smoke/v1",
         "status":"CPU_REAL_CONTROLLER_NATIVE_WORKER_QUEUE_PASS",
         "output_images":output,"idempotent_replay_verified":True,
         "openapi_endpoint_verified":True,"model_downloads":0,
         "gpu_inference_attested":False,"real_generator_attested":False,
         "human_accessibility_qualified":False},sort_keys=True))

if __name__=="__main__":
    main()
