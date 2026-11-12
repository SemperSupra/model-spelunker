#!/usr/bin/env python3
"""Bounded, native ComfyUI API and PyTorch toy CNN integration smoke.

This calls real /object_info, /prompt, /history, /view. No model downloads,
external requests, GPU claims, or global workflow permissions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

class SmokeError(RuntimeError):
    pass

def json_request(base: str, path: str, payload=None, timeout=8):
    data = None if payload is None else json.dumps(payload, sort_keys=True).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data, headers={"Content-Type":"application/json", "Accept":"application/json"},
        method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read(1_000_001)
        if len(body) > 1_000_000 or response.status != 200:
            raise SmokeError("RESPONSE_BOUNDED_OR_SUCCESS_REQUIRED")
    return json.loads(body)

def graph(seed: int, variant: str) -> dict:
    if variant not in ("base", "modified") or type(seed) is not int or seed < 0:
        raise SmokeError("FIXTURE_INVALID")
    return {
        "1": {"class_type":"TinyTorchConditionerFixture",
              "inputs":{"seed":seed,"variant":variant,"size":64}},
        "2": {"class_type":"SaveImage",
              "inputs":{"images":["1",0],"filename_prefix":"qualification-toy"}},
    }

def run(base: str, deadline_seconds: int=100) -> dict:
    deadline = time.monotonic() + deadline_seconds
    while True:
        try:
            classes=json_request(base, "/object_info/TinyTorchConditionerFixture")
            if "TinyTorchConditionerFixture" in classes:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        if time.monotonic() > deadline:
            raise SmokeError("COMFYUI_NODE_BOOT_TIMEOUT")
        time.sleep(1)
    statuses = []
    for seed,variant in ((31,"base"),(31,"modified")):
        response = json_request(base,"/prompt",{"prompt":graph(seed,variant),"client_id":"qualification-toy-only"})
        pid = response.get("prompt_id")
        if not isinstance(pid,str) or len(pid)>128:
            raise SmokeError("NO_NATIVE_PROMPT_ID")
        statuses.append((pid,variant))
    queued = json_request(base,"/queue")
    if not isinstance(queued,dict) or "queue_running" not in queued or "queue_pending" not in queued:
        raise SmokeError("NATIVE_QUEUE_NOT_AVAILABLE")
    observed=[]
    for pid,variant in statuses:
        while time.monotonic()<deadline:
            history=json_request(base, "/history/"+urllib.parse.quote(pid,safe=""))
            rec=history.get(pid)
            if rec:
                status=rec.get("status",{})
                if status.get("status_str")=="error" or status.get("completed") is False:
                    raise SmokeError("WORKFLOW_FAILED")
                images=rec.get("outputs",{}).get("2",{}).get("images",[])
                if images:
                    f=images[0]
                    query=urllib.parse.urlencode({"filename":f["filename"],"subfolder":f.get("subfolder",""),"type":f.get("type","output")})
                    with urllib.request.urlopen(base.rstrip("/")+"/view?"+query,timeout=15) as r:
                        png=r.read(1_000_001)
                    if len(png)>1_000_000 or not png.startswith(bytes.fromhex("89504e470d0a1a0a")) or len(png)<28:
                        raise SmokeError("PNG_INVALID")
                    width,height=struct.unpack(">II",png[16:24])
                    if (width,height)!=(64,64):
                        raise SmokeError("PNG_DIMENSIONS_MISMATCH")
                    observed.append({"variant":variant,"png_sha256":hashlib.sha256(png).hexdigest(),
                                     "png_bytes":len(png),"width":width,"height":height})
                    break
            time.sleep(1)
        else:
            raise SmokeError("NATIVE_QUEUE_WORKFLOW_TIMEOUT")
    if len(observed)!=2 or observed[0]["png_sha256"]==observed[1]["png_sha256"]:
        raise SmokeError("TREATMENT_CONTROL_NOT_DISCRIMINATED")
    return {"schema":"comfy-conditioning-toy-smoke/v1",
            "status":"CPU_TOY_GRAPH_AND_QUEUE_PASS",
            "model_kind":"random-init-tiny-conv1x1-fixed-weights-not-real-diffusion",
            "output_images":observed, "native_prompts_observed":2,
            "model_downloads":0,"gpu_inference_attested":False,
            "real_generator_attested":False,"heretic_quality_attested":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",default="http://127.0.0.1:8188")
    p.add_argument("--deadline",type=int,default=100)
    opts=p.parse_args()
    try:
        result=run(opts.base,opts.deadline)
    except (SmokeError, urllib.error.URLError, KeyError, TypeError, ValueError) as exc:
        reason=str(exc) if isinstance(exc,SmokeError) else "NATIVE_RUNTIME_UNEXPECTED_ERROR"
        print(json.dumps({"status":"HOLD","reason":reason,"real_generator_attested":False}))
        raise SystemExit(2)
    print(json.dumps(result,sort_keys=True))
if __name__=="__main__":
    main()
