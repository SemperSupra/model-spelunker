#!/usr/bin/env python3
"""Synthetic public OpenAI SSE tool-call oracle with trailing usage-only chunk.

This is intentionally NOT a model. It validates the native CLI's handling of
OpenAI-compatible stream_options.include_usage, tool_calls and finish events.
"""
import argparse,json,os,sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"qwencode_wire"))
from mock_provider import PublicServer,Handler,respond,chunk,completion,MAX_BODY


def sse_response(body,file_path):
    message,finish,state=respond(body,file_path)
    model=str(body.get("model","qwen-public-usage"))
    deltas=[{"role":"assistant"}]
    if "tool_calls" in message:
        deltas.append({"tool_calls":[dict(tc,index=i) for i,tc in enumerate(message["tool_calls"])]})
    else:
        deltas.append({"content":message["content"]})
    events=[chunk(model,d) for d in deltas]
    events.append(chunk(model,{},finish))
    # A conforming trailing choices:[] usage chunk may arrive *after* finish.
    if (body.get("stream_options") or {}).get("include_usage") is True:
        events.append({"id":"chatcmpl-public-synthetic","object":"chat.completion.chunk",
                       "created":1,"model":model,"choices":[],
                       "usage":{"prompt_tokens":100,"completion_tokens":5,"total_tokens":105}})
    return "".join("data: "+json.dumps(e,separators=(",",":"))+"\n\n" for e in events)+"data: [DONE]\n\n",state


class UsageHandler(Handler):
    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/chat/completions","/chat/completions"):
            self.send_json(404,{"error":"strict synthetic endpoint only"})
            return
        try:
            count=int(self.headers.get("Content-Length","0"))
            if count<2 or count>MAX_BODY:
                self.send_json(413,{"error":"request bound"})
                return
            request=json.loads(self.rfile.read(count))
            self.server.record({
                "phase":"protocol-request",
                "request_bytes":count,
                "stream":request.get("stream") is True,
                "usage_requested":(request.get("stream_options") or {}).get("include_usage") is True,
                "tool_advertised":any(t.get("function",{}).get("name")=="read_file"
                    for t in request.get("tools") or []),
                "raw_prompts_retained":False
            })
            if request.get("stream") is True:
                body,state=sse_response(request,self.server.filepath)
                self.server.record({
                    "phase":state["phase"],
                    "tool_advertised":state["tool_advertised"],
                    "usage_trailer_emitted":(request.get("stream_options") or {}).get("include_usage") is True,
                    "nonce_retained":False
                })
                out=body.encode()
                self.send_response(200)
                self.send_header("Content-Type","text/event-stream")
                self.send_header("Content-Length",str(len(out)))
                self.send_header("Cache-Control","no-cache")
                self.end_headers()
                self.wfile.write(out)
                self.wfile.flush()
                return
            message,finish,state=respond(request,self.server.filepath)
            self.server.record({"phase":state["phase"],"nonce_retained":False})
            self.send_json(200,completion(str(request.get("model","qwen-public-usage")),
                                         message,finish))
        except (ValueError,TypeError,KeyError,AttributeError):
            self.send_json(400,{"error":"malformed request"})


class UsageServer(PublicServer):
    def __init__(self,filepath,evidence):
        import threading
        from http.server import ThreadingHTTPServer
        # Initialize directly with the replacement HTTP Handler.
        ThreadingHTTPServer.__init__(self,("127.0.0.1",0),UsageHandler)
        self.filepath=Path(filepath).resolve()
        self.evidence=Path(evidence)
        self.lock=threading.Lock()
        self.events=[]


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--file",required=True)
    p.add_argument("--port-file",required=True)
    p.add_argument("--state",required=True)
    o=p.parse_args()
    if not Path(o.file).is_file():
        raise SystemExit("MISSING_SYNTHETIC_FIXTURE")
    server=UsageServer(o.file,o.state)
    Path(o.port_file).write_text(str(server.server_port))
    try: server.serve_forever(poll_interval=0.1)
    finally:server.server_close()


if __name__=="__main__":main()
