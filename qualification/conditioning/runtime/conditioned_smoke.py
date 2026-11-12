#!/usr/bin/env python3
"""True two-Torch-module Comfy DAG integration smoke (no pretrained models).

Feeds an allowlisted prompt through nn.Embedding, then its tensor into a
separately instantiated nn.Conv2d image node. Paired seed/prompt/generator are
frozen; only the synthetic conditioner variant changes.
"""
import hashlib
import json
import struct
import time
from urllib import error,parse,request

from smoke import json_request, SmokeError


def graph(variant: str):
    if variant not in ("base","modified"):
        raise SmokeError("SYNTHETIC_VARIANT_DENIED")
    return {
        "1":{"class_type":"TinyTextEncoderFixture","inputs":{
            "prompt":"red-square","variant":variant}},
        "2":{"class_type":"TinyConditionedImageFixture","inputs":{
            "embedding":["1",0],"seed":71,"size":64}},
        "3":{"class_type":"SaveImage","inputs":{
            "images":["2",0],"filename_prefix":"toy-conditioning-abi"}},
    }


def run(base="http://127.0.0.1:8188", timeout_seconds=160):
    deadline=time.monotonic()+timeout_seconds
    while time.monotonic()<deadline:
        try:
            a=json_request(base,"/object_info/TinyTextEncoderFixture")
            b=json_request(base,"/object_info/TinyConditionedImageFixture")
            if "TinyTextEncoderFixture" in a and "TinyConditionedImageFixture" in b:
                break
        except (OSError,TimeoutError,ValueError):
            pass
        time.sleep(0.5)
    else:
        raise SmokeError("TWO_MODEL_NODE_REGISTRY_UNAVAILABLE")

    results=[]
    for variant in ("base","modified"):
        ret=json_request(base,"/prompt",{"client_id":"toy-abi-qualification-only","prompt":graph(variant)})
        pid=ret.get("prompt_id")
        if type(pid) is not str or len(pid)>128 or len(pid)<8:
            raise SmokeError("NATIVE_PROMPT_NOT_ADMITTED")
        while time.monotonic()<deadline:
            record=json_request(base,"/history/"+parse.quote(pid,safe="")).get(pid)
            if record is None:
                time.sleep(0.5)
                continue
            status=record.get("status",{}).get("status_str")
            if status=="error":
                raise SmokeError("TWO_MODULE_COMFY_GRAPH_FAILED")
            if status!="success":
                time.sleep(0.5)
                continue
            images=record.get("outputs",{}).get("3",{}).get("images",[])
            if len(images)!=1:
                raise SmokeError("TWO_MODULE_IMAGE_COUNT")
            f=images[0]
            if f.get("type")!="output":
                raise SmokeError("TWO_MODULE_OUTPUT_TYPE")
            q=parse.urlencode({"filename":f["filename"],"type":"output",
                               "subfolder":f.get("subfolder","")})
            with request.urlopen(base.rstrip("/")+"/view?"+q,timeout=10) as resp:
                raw=resp.read(1_000_001)
            if (len(raw)>1_000_000 or raw[:8]!=bytes.fromhex("89504e470d0a1a0a") or
                struct.unpack(">II",raw[16:24])!=(64,64)):
                raise SmokeError("TWO_MODULE_PNG_INVALID")
            results.append({"variant":variant,"sha256":hashlib.sha256(raw).hexdigest(),
                            "bytes":len(raw)})
            break
        else:
            raise SmokeError("TWO_MODULE_QUEUE_TIMEOUT")
    if results[0]["sha256"]==results[1]["sha256"]:
        raise SmokeError("CONDITIONER_TREATMENT_NOT_OBSERVABLE")
    return {"schema":"conditioning-two-torch-models/v1",
            "status":"NATIVE_TORCH_EMBEDDING_TO_IMAGE_MODULE_PASS",
            "frozen_prompt":"red-square","frozen_seed":71,
            "generator_module":"tiny-untrained-conv2d",
            "conditioner_module":"tiny-untrained-embedding",
            "paired_outputs":results,
            "real_llm":False,"diffusion_generator":False,"gpu_inference":False,
            "actual_heretic_or_flux":False,"model_weights_downloaded":False}


if __name__=="__main__":
    try:
        print(json.dumps(run(),sort_keys=True))
    except (SmokeError,OSError,KeyError,ValueError,TypeError,error.URLError) as exc:
        code=str(exc) if isinstance(exc,SmokeError) else "SYNTHETIC_GRAPH_RUNTIME_HOLD"
        print(json.dumps({"status":"HOLD","reason":code}))
        raise SystemExit(2)
