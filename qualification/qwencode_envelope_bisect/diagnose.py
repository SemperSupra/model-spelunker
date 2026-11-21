#!/usr/bin/env python3
"""R6-B public CPU-only intermediate system prompt × tool-count crossover.

Each profile is a single real model request with synthetic harmless input,
not Qwen CLI agent execution. Imports previously qualified public direct SSE
parser/validator; records no raw prompt or model response.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

TOP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOP/"qwencode_model_diagnostics"))
sys.path.insert(0,str(TOP/"qwencode_context_envelope"))
from probe import parse_stream,valid_tool
from compare import prepare

PROFILES=("short-three","medium-one","medium-three")
SYSTEM_CHARS=8000
MAX_UPSTREAM_BYTES=5_000_000


def make_profile(profile):
    if profile not in PROFILES:
        raise ValueError("unsupported public model crossover profile")
    request=prepare("small")
    # Duplicate only *tool schemas*, not the large profile's artificial
    # description padding; keep the same actual file tool and user question.
    if profile.endswith("three"):
        orig=request["tools"][0]
        for name in ("glob","list_directory"):
            request["tools"].append({
                "type":"function",
                "function":{
                    "name":name,
                    "description":"Public synthetic unused tool; no actual execution",
                    "parameters":{"type":"object","properties":{
                        "file_path":{"type":"string"}},"required":["file_path"]}
                }
            })
        assert request["tools"][0]==orig
    if profile.startswith("medium"):
        base=request["messages"][0]["content"]
        pad=" Neutral synthetic task-bound instruction, no real data. "
        request["messages"][0]["content"]=(base + pad*180)[:SYSTEM_CHARS].ljust(SYSTEM_CHARS)
    request["max_tokens"]=256
    return request


def one_rep(profile):
    request=make_profile(profile)
    raw=json.dumps(request,separators=(",",":")).encode()
    row={"profile":profile,"model":request["model"],
         "input_bytes":len(raw),
         "system_content_chars":len(request["messages"][0]["content"]),
         "tools_advertised":len(request["tools"]),
         "stream":request["stream"],"reasoning_effort":request["reasoning_effort"],
         "max_tokens":request["max_tokens"],
         "data_class":"PUBLIC_SYNTHETIC"}
    started=time.monotonic()
    try:
        req=urllib.request.Request(
            "http://127.0.0.1:11434/v1/chat/completions",
            data=raw,method="POST",headers={
                "Content-Type":"application/json",
                "Authorization":"Bearer ollama"})
        with urllib.request.urlopen(req,timeout=100) as res:
            wire=res.read(MAX_UPSTREAM_BYTES+1)
        if len(wire)>MAX_UPSTREAM_BYTES:
            raise ValueError("response-byte-budget-exceeded")
        calls,finish,deltas=parse_stream(wire.decode())
        matched=valid_tool(calls)
        row.update({"finish_reason":finish,"response_tool_call_count":len(calls),
                    "read_file_valid":matched,"stream_choice_events":deltas,
                    "result":"PASS" if matched else "FAIL"})
    except (urllib.error.URLError,TimeoutError,OSError,ValueError) as error:
        row.update({"result":"FAIL","failure_type":type(error).__name__,
                    "read_file_valid":False})
    row["wall_seconds"]=round(time.monotonic()-started,2)
    return row


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--profile",choices=PROFILES,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    row=one_rep(args.profile)
    result={
        "schema":"qwen-public-intermediate-envelope/v1",
        "status":row["result"],
        "runtime":"STANDARD_PUBLIC_GHA_CPU",
        "provider":"PINNED_OLLAMA_QWEN3_1P7B_LOOPBACK",
        "full_qwen_agent":"NOT_TESTED",
        "tool_execution":"NOT_TESTED",
        "private_credentials":"NOT_USED",
        "cases":[row]
    }
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
    if result["status"]!="PASS":
        raise SystemExit(1)


if __name__=="__main__":
    main()
