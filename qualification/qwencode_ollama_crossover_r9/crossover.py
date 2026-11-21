#!/usr/bin/env python3
"""Direct real Ollama one-field OpenAI SSE crossover. Never retain prompt or model content."""
import argparse,json,os,sys,urllib.request
MODEL=os.environ.get("QWEN_MODEL","qwen3:1.7b")
URL="http://127.0.0.1:11434/v1/chat/completions"
TOOL={"type":"function","function":{"name":"read_file","description":"Read a synthetic file by path","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}}
def request(include_usage):
    req={"model":MODEL,"stream":True,"messages":[{"role":"system","content":"Use the provided function for the task."},{"role":"user","content":"Call read_file with path /tmp/synthetic.txt. Do not guess the contents."}],"tools":[TOOL],"temperature":0,"max_tokens":128}
    if include_usage:req["stream_options"]={"include_usage":True}
    return req
def classify(lines):
    result={"chunks":0,"usage_only":0,"tool_deltas":0,"content_deltas":0,"finish_reasons":[],"invalid":0}
    for line in lines:
        if not line.startswith(b"data: "):continue
        data=line[6:].strip()
        if data==b"[DONE]":continue
        try:event=json.loads(data)
        except (ValueError,UnicodeDecodeError):result["invalid"]+=1;continue
        result["chunks"]+=1
        choices=event.get("choices")
        if not isinstance(choices,list):result["invalid"]+=1;continue
        if not choices:
            if isinstance(event.get("usage"),dict):result["usage_only"]+=1
            else:result["invalid"]+=1
        for choice in choices:
            delta=choice.get("delta",{})
            if not isinstance(delta,dict):result["invalid"]+=1;continue
            if delta.get("content"):result["content_deltas"]+=1
            for call in delta.get("tool_calls",[]) or []:
                if isinstance(call,dict) and type(call.get("index")) is int:result["tool_deltas"]+=1
            if choice.get("finish_reason") is not None:result["finish_reasons"].append(choice["finish_reason"])
    result["tool_selected"]=result["tool_deltas"]>0
    return result
def selftest():
    assert "stream_options" not in request(False)
    assert request(True)["stream_options"]=={"include_usage":True}
    a=classify([b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"SENSITIVE"}}]},"finish_reason":null}]}',b'data: {"choices":[],"usage":{"total_tokens":9}}',b'data: [DONE]'])
    assert a["tool_selected"] and a["usage_only"]==1 and "SENSITIVE" not in json.dumps(a)
    assert classify([b'data: {"choices":[{"delta":{"content":"SENSITIVE"},"finish_reason":"stop"}]}'])["content_deltas"]==1
    assert classify([b'data: {"choices":null}'])["invalid"]==1
    print(json.dumps({"status":"PASS","scope":"synthetic offline parser and single-field mutation"}))
def live():
    results=[]
    for include in (False,True):
        req=json.dumps(request(include)).encode("utf-8")
        try:
            call=urllib.request.Request(URL,data=req,headers={"Content-Type":"application/json"},method="POST")
            with urllib.request.urlopen(call,timeout=100) as stream: result=classify(stream)
            result.update(usage_requested=include,request_bytes=len(req))
        except Exception as exc:result={"usage_requested":include,"status":"ERROR","error_type":type(exc).__name__}
        results.append(result)
    ok=all(r.get("tool_selected") and not r.get("invalid") for r in results)
    print(json.dumps({"status":"PASS" if ok else "FAIL","scope":"direct real Ollama tool selection only, not native Qwen Code","results":results},sort_keys=True))
    if not ok:sys.exit(1)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--live",action="store_true");a=p.parse_args()
    if a.selftest:selftest()
    elif a.live:live()
    else:p.error("select --selftest or --live")
