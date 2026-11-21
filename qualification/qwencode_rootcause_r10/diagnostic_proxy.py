#!/usr/bin/env python3
"""Synthetic-only local OpenAI-compatible Qwen↔Ollama proxy/metadata observer.

For public disposable GHA only; never forwards remote/private endpoints,
never stores prompts, bearer tokens or model output. This is a diagnostic,
NOT a credential broker, scheduler, model server or policy enforcement layer.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error


def normalize_request(obj,mode):
    if mode not in ("baseline","compact_system","compact_tools","compact_both","compact_schema","compact_schema_budget","compact_all_prompt","compact_all_prompt_budget","force_256_full","force_256_compact"):
        raise ValueError("unsupported normalization mode")
    if mode in ("compact_system","compact_both","compact_schema","compact_schema_budget","compact_all_prompt","compact_all_prompt_budget","force_256_compact"):
        compact={"role":"system","content":"Read fixture.txt using read_file. Return the exact file text. Do not guess."}
        obj["messages"]=[compact]+[m for m in obj.get("messages",[]) if m.get("role") not in ("system","developer")]
    if mode in ("compact_tools","compact_both","compact_schema","compact_schema_budget","compact_all_prompt","compact_all_prompt_budget","force_256_compact"):
        obj["tools"]=[t for t in obj.get("tools",[]) if t.get("type")=="function" and t.get("function",{}).get("name")=="read_file"]
    if mode in ("compact_schema","compact_schema_budget","compact_all_prompt","compact_all_prompt_budget","force_256_compact"):
        if len(obj.get("tools",[]))!=1 or obj["tools"][0]["function"]["name"]!="read_file":
            raise ValueError("required read_file tool missing")
        obj["tools"][0]["function"]["description"]="Read one local file"
        obj["tools"][0]["function"]["parameters"]={
            "type":"object",
            "properties":{"file_path":{"type":"string","description":"file path"}},
            "required":["file_path"]
        }
    if mode in ("compact_all_prompt","compact_all_prompt_budget","force_256_compact"):
        for message in obj.get("messages",[]):
            if message.get("role")=="user":
                message["content"]="Call read_file using file_path fixture.txt, then return its exact contents."
    if mode in ("force_256_full","force_256_compact"):
        obj["max_tokens"]=256
    return obj


class Proxy(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,state):
        super().__init__(address,Handler)
        self.state=Path(state)
        self.events=[]
        self.lock=threading.Lock()
    def record(self,event):
        with self.lock:
            self.events.append(event)
            self.state.write_text(json.dumps({
                "schema":"qwen-public-harness-wire-observer/v1",
                "source_class":"PUBLIC_SYNTHETIC",
                "provider":"OLLAMA_LOOPBACK_ONLY",
                "raw_prompts_or_tokens":"NEVER_RETAINED",
                "events":self.events
            },sort_keys=True,indent=2)+"\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,fmt,*args):
        pass
    def as_json(self,code,value):
        data=json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if self.path in ("/v1/models","/models"):
            self.as_json(200,{"object":"list","data":[
                {"id":"qwen3:1.7b","object":"model","owned_by":"local-synthetic-test"}
            ]})
        elif self.path=="/health":
            self.as_json(200,{"status":"OK","proxy":"LOOPBACK_ONLY"})
        else:
            self.as_json(404,{"error":"unsupported path"})
    def do_POST(self):
        if self.path!="/v1/chat/completions":
            self.server.record({"phase":"unexpected-path"})
            self.as_json(404,{"error":"unexpected path"})
            return
        length=int(self.headers.get("Content-Length","0"))
        if length<2 or length>8_000_000:
            self.as_json(413,{"error":"request byte bound"})
            return
        payload=self.rfile.read(length)
        started=time.monotonic()
        try:
            obj=json.loads(payload)
        except ValueError:
            self.as_json(400,{"error":"bad JSON"})
            return
        original_bytes=len(payload)
        original_budget=obj.get("max_tokens")
        mode=self.server.mode
        obj=normalize_request(obj,mode)
        if mode!="baseline":
            payload=json.dumps(obj,separators=(",",":")).encode("utf-8")
        messages=obj.get("messages") or []
        tools=obj.get("tools") or []
        event={
            "phase":"upstream-request",
            "request_bytes":len(payload),
            "original_request_bytes":original_bytes,
            "mode":mode,
            "request_keys":sorted(obj.keys()),
            "message_role_lengths":[{"role":m.get("role"),"json_chars":len(json.dumps(m.get("content","")))} for m in messages],
            "requested_output_budget":obj.get("max_tokens"),
            "original_output_budget":original_budget,
            "messages_count":len(messages),
            "system_content_chars":sum(len(json.dumps(m.get("content","")))
                for m in messages if m.get("role") in ("system","developer")),
            "tools_count":len(tools),
            "tool_names":sorted(str(t.get("function",{}).get("name",""))
                for t in tools if t.get("type")=="function")[:70],
            "stream":obj.get("stream") is True,
            "model":str(obj.get("model")),
            "reasoning_effort":str(obj.get("reasoning_effort","NOT_SENT")),
            "response_elapsed_seconds":None,
            "sse_events":0,
            "sse_tool_delta_events":0,
            "sse_content_deltas":0,
            "sse_reasoning_deltas":0,
            "finish_reasons":[],
            "first_sse_event_seconds":None,
            "result":"IN_PROGRESS"
        }
        self.server.record(event.copy())
        try:
            request=urllib.request.Request(
                "http://127.0.0.1:11434/v1/chat/completions",
                data=payload,method="POST",
                headers={"Content-Type":"application/json",
                         "Authorization":"Bearer ollama"})
            with urllib.request.urlopen(request,timeout=170) as response:
                self.send_response(response.status)
                self.send_header("Content-Type",response.headers.get(
                    "Content-Type","application/json"))
                self.send_header("Cache-Control","no-cache")
                self.send_header("Connection","close")
                self.end_headers()
                self.close_connection=True
                if event["stream"]:
                    for line in response:
                        if line.startswith(b"data: "):
                            event["sse_events"]+=1
                            if event["first_sse_event_seconds"] is None:
                                event["first_sse_event_seconds"]=round(
                                    time.monotonic()-started,3)
                            # Tool delta detection only; never retain text, ids
                            # or arguments.
                            if line.startswith(b"data: {"):
                                try:
                                    chunk=json.loads(line[6:])
                                    for choice in chunk.get("choices",[]) or []:
                                        delta=choice.get("delta") or {}
                                        if delta.get("tool_calls"):
                                            event["sse_tool_delta_events"]+=len(delta["tool_calls"])
                                        if delta.get("content"):
                                            event["sse_content_deltas"]+=1
                                        if delta.get("reasoning") or delta.get("reasoning_content"):
                                            event["sse_reasoning_deltas"]+=1
                                        if choice.get("finish_reason") is not None:
                                            event["finish_reasons"].append(choice["finish_reason"])
                                except (ValueError,TypeError,AttributeError):
                                    event["sse_parse_error"]=True
                        self.wfile.write(line)
                        self.wfile.flush()
                else:
                    blob=response.read(8_000_000)
                    self.wfile.write(blob)
                    self.wfile.flush()
                event["result"]="FORWARDED"
        except (OSError,urllib.error.URLError,ValueError,TimeoutError) as exc:
            event["result"]="FORWARD_FAILURE"
            event["failure_type"]=type(exc).__name__
        finally:
            event["response_elapsed_seconds"]=round(time.monotonic()-started,3)
            self.server.record(event)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--port-file",required=True)
    p.add_argument("--state",required=True)
    p.add_argument("--mode",choices=("baseline","compact_system","compact_tools","compact_both","compact_schema","compact_schema_budget","compact_all_prompt","compact_all_prompt_budget","force_256_full","force_256_compact"),required=True)
    options=p.parse_args()
    server=Proxy(("127.0.0.1",0),options.state)
    server.mode=options.mode
    Path(options.port_file).write_text(str(server.server_port))
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()


if __name__=="__main__":
    main()
