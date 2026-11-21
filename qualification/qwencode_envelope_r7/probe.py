#!/usr/bin/env python3
"""Source-neutral real Qwen3/Ollama streamed tool-call envelope boundary probes."""
import argparse,json,sys,time,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"qwencode_envelope_bisect"))
from diagnose import make_profile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"qwencode_model_diagnostics"))
from probe import parse_stream,valid_tool

PROFILES={"r7-12kb":12000,"r7-19kb":19000,"r7-25kb":25000}
TARGET_MODEL="qwen3:1.7b"
ENDPOINT="http://127.0.0.1:11434/v1/chat/completions"


def build(profile):
    if profile not in PROFILES:
        raise ValueError("not an admitted public profile")
    base=make_profile("short-three")
    target=PROFILES[profile]
    # Exact ASCII byte count; one changed variable: harmless public synthetic
    # system text. The user task, tool schema, output cap and stream identical.
    original=base["messages"][0]["content"]
    fixed=json.dumps(base,separators=(",",":")).encode()
    remaining=target-len(fixed)
    if remaining<0:
        raise ValueError("invalid target below base payload")
    base["messages"][0]["content"]=original + (" X"*(remaining//2)) + ("X" if remaining%2 else "")
    assert len(json.dumps(base,separators=(",",":")).encode())==target
    return base


def run(profile):
    payload=build(profile)
    binary=json.dumps(payload,separators=(",",":")).encode()
    start=time.monotonic()
    row={"profile":profile,"request_bytes":len(binary),
         "system_chars":len(payload["messages"][0]["content"]),
         "tools":len(payload["tools"]),"stream":True,"reasoning_effort":"none",
         "model":TARGET_MODEL,"read_file_valid":False}
    try:
        request=urllib.request.Request(ENDPOINT,data=binary,method="POST",
            headers={"Content-Type":"application/json","Authorization":"Bearer ollama"})
        with urllib.request.urlopen(request,timeout=120) as resp:
            data=resp.read(5_000_001)
        if len(data)>5_000_000:
            raise ValueError("response byte bound")
        calls,reason,chunks=parse_stream(data.decode())
        row.update({"finish_reason":reason,"stream_chunks":chunks,
                    "read_file_valid":valid_tool(calls),
                    "tool_call_count":len(calls)})
        row["result"]="PASS" if row["read_file_valid"] else "FAIL"
    except (urllib.error.URLError,TimeoutError,OSError,ValueError) as err:
        row.update({"result":"FAIL","error_type":type(err).__name__})
    row["wall_seconds"]=round(time.monotonic()-start,2)
    return row


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--profile",choices=sorted(PROFILES),required=True)
    p.add_argument("--output",required=True)
    x=p.parse_args()
    row=run(x.profile)
    report={"schema":"qwen-r7-public-envelope/v1",
            "provider":"PINNED_OLLAMA_QWEN3_1P7B_LOCAL_CPU",
            "data_class":"PUBLIC_SYNTHETIC",
            "full_qwen_cli":"NOT_TESTED_IN_THIS_BAND",
            "tool_execution":"NOT_TESTED",
            "site_models":"NOT_TESTED",
            "row":row,"verdict":row["result"]}
    Path(x.output).write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(json.dumps(report,sort_keys=True))
    if report["verdict"]!="PASS":raise SystemExit(1)

if __name__=="__main__":main()
