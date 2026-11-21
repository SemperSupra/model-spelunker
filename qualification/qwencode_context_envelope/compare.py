#!/usr/bin/env python3
"""Real Ollama qwen3:1.7b tool-SSE context-envelope crossover on PUBLIC GHA.

The only variable is synthetic system/tool-schema length (small vs large).
Never records prompts, model content, credentials, or endpoint identities.
"""
import argparse
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
import sys

# Reuse already-qualified public SSE semantics from preceding PR #230.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"qwencode_model_diagnostics"))
from probe import parse_stream, valid_tool

TARGET_CHARS=14459
TARGET_REQUEST_BYTES=29365


def prepare(profile):
    assert profile in ("small","large")
    system="Public-synthetic test. Use the read_file function on fixture.txt and do not claim the file was read yet."
    if profile=="large":
        # Synthetic repeated task-neutral instructions, NOT a copied real prompt.
        system=(system+" "+("Public synthetic harmless instruction ballast. " * 500))[:TARGET_CHARS]
        system=system.ljust(TARGET_CHARS, " ")
    def tool(name,desc):
        return {
          "type":"function","function":{"name":name,"description":desc,
          "parameters":{"type":"object","properties":{"file_path":{"type":"string"}},
                        "required":["file_path"]}}
        }
    tools=[tool("read_file","Read the named file in a synthetic workspace")]
    if profile=="large":
        tools.extend([tool("glob","Synthetic file pattern tool not executable"),
                      tool("list_directory","Synthetic directory catalog not executable")])
    payload={
        "model":"qwen3:1.7b",
        "messages":[{"role":"system","content":system},
                    {"role":"user","content":"Call read_file with file_path exactly fixture.txt; do not invent a file value."}],
        "tools":tools,"tool_choice":"auto",
        "reasoning_effort":"none","stream":True,
        "temperature":0,"max_tokens":256
    }
    if profile=="large":
        # Additional neutral schema bytes to approach the *observed* Qwen 29.4KB
        # serialized envelope without copying any original private/user text.
        current=len(json.dumps(payload,separators=(",",":")).encode())
        gap=TARGET_REQUEST_BYTES-current
        if gap>0:
            payload["tools"][0]["function"]["description"]+=("Z"*gap)
    return payload


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--profile",choices=("small","large"),required=True)
    parser.add_argument("--receipt",type=Path,required=True)
    options=parser.parse_args()
    payload=prepare(options.profile)
    body=json.dumps(payload,separators=(",",":")).encode()
    started=time.monotonic()
    row={"profile":options.profile,"request_bytes":len(body),
         "system_content_chars":len(payload["messages"][0]["content"]),
         "tools_advertised":len(payload["tools"]),
         "stream":True, "reasoning_effort":"none"}
    try:
        request=urllib.request.Request("http://127.0.0.1:11434/v1/chat/completions",
            data=body,
            headers={"Content-Type":"application/json",
                     "Authorization":"Bearer ollama"},method="POST")
        with urllib.request.urlopen(request,timeout=120) as resp:
            raw=resp.read(5_000_000)
        calls,finish,chunks=parse_stream(raw.decode())
        row.update({
            "tool_call_valid":valid_tool(calls),
            "tool_call_count":len(calls),
            "finish_reason":str(finish),
            "sse_choice_events":chunks,
            "result":"PASS" if valid_tool(calls) else "FAIL",
            "response_raw":"NOT_RETAINED"
        })
    except (ValueError,OSError,urllib.error.URLError,TimeoutError) as exc:
        row.update({"result":"FAIL",
                    "failure_type":type(exc).__name__,
                    "response_raw":"NOT_RETAINED"})
    row["wall_seconds"]=round(time.monotonic()-started,2)
    receipt={
        "schema":"qwen-public-context-envelope/v1",
        "provider":"OLLAMA_QWEN3_1P7B_PUBLIC_RUNNER",
        "profile":options.profile,
        "model_inference":"ACTUAL_DIRECT_MODEL",
        "tool_execution":"NOT_TESTED",
        "full_qwen_agent":"NOT_TESTED",
        "private_input":"NONE",
        "cases":[row],
        "verdict":row["result"]
    }
    options.receipt.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print(json.dumps(receipt,sort_keys=True))
    if receipt["verdict"]!="PASS":
        raise SystemExit(1)


if __name__=="__main__":
    main()
