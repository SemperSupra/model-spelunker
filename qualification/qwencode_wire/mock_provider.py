#!/usr/bin/env python3
"""Loopback-only OpenAI-compatible synthetic Qwen tool-call oracle.

This fake provider is NOT a model and must never be counted as model inference
qualification. It proves only CLI/provider/tool marshaling on a hidden file.
"""
import argparse
import json
import os
from pathlib import Path
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

HEXVALUE = re.compile(r"VALUE=([a-f0-9]{24})")
MAX_BODY = 2_000_000


def tool_names(body):
    return sorted(str(t.get("function", {}).get("name", "")) for t in body.get("tools", [])
                  if t.get("type") == "function")


def find_tool_result(body):
    """Only an actual tool role response may supply the hidden value."""
    for message in body.get("messages", []):
        if message.get("role") != "tool":
            continue
        payload = message.get("content", "")
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        match = HEXVALUE.search(raw)
        if match:
            return "VALUE=" + match.group(1)
    return None


def chunk(model, delta, finish=None):
    return {"id": "chatcmpl-publicsynthetic",
            "object": "chat.completion.chunk", "created": 1, "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def completion(model, message, finish):
    return {"id": "chatcmpl-publicsynthetic",
            "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}


def respond(body, file_path):
    names = tool_names(body)
    model = body.get("model", "qwen-public-wire")
    value = find_tool_result(body)
    if value:
        return {"role": "assistant", "content": value}, "stop", {
            "phase": "tool-result-seen",
            "reported_value": True,
            "tool_advertised": "read_file" in names
        }
    if "read_file" not in names:
        return {"role": "assistant", "content": "READ_FILE_TOOL_NOT_ADVERTISED"}, "stop", {
            "phase": "missing-tool",
            "reported_value": False,
            "tool_advertised": False
        }
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_public_read_01",
            "type": "function",
            "function": {"name": "read_file",
                         "arguments": json.dumps({"file_path": str(file_path)})}
        }]
    }, "tool_calls", {
        "phase": "read-file-call-sent",
        "reported_value": False,
        "tool_advertised": True
    }


class PublicServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, filepath, evidence):
        super().__init__(address, Handler)
        self.filepath = Path(filepath).resolve()
        self.evidence = Path(evidence)
        self.lock = threading.Lock()
        self.events = []

    def record(self, data):
        with self.lock:
            self.events.append(data)
            self.evidence.write_text(json.dumps({
                "schema": "qwen-public-wire-observation/v1",
                "endpoint": "LOOPBACK",
                "model_inference": "NOT_TESTED_FAKE_PROVIDER",
                "events": self.events
            }, indent=2) + "\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # Do not log prompts, HTTP auth or large protocol payloads.
        pass

    def send_json(self, status, value):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path in ("/v1/models", "/models"):
            self.send_json(200, {"object": "list", "data": [
                {"id": "qwen-public-wire", "object": "model", "owned_by": "public-synthetic"}
            ]})
        elif self.path == "/health":
            self.send_json(200, {"status": "OK", "type": "synthetic-only"})
        else:
            self.send_json(404, {"error": {"message": "unknown synthetic route", "type": "invalid_request_error"}})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self.server.record({"phase": "unsupported-post-route"})
            self.send_json(404, {"error": {"message": "unsupported synthetic endpoint", "type": "invalid_request_error"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > MAX_BODY:
                self.send_json(413, {"error": {"message": "payload bound", "type": "invalid_request_error"}})
                return
            body = json.loads(self.rfile.read(length))
            message, finish, state = respond(body, self.server.filepath)
            state["stream"] = body.get("stream") is True
            state["tools_total"] = len(tool_names(body))
            self.server.record(state)
            if body.get("stream") is True:
                model = body.get("model", "qwen-public-wire")
                deltas = [{"role": "assistant"}]
                if "tool_calls" in message:
                    deltas.append({"tool_calls": [{**tc, "index": i}
                                    for i, tc in enumerate(message["tool_calls"])]})
                else:
                    deltas.append({"content": message["content"]})
                events = [chunk(model, delta) for delta in deltas]
                events.append(chunk(model, {}, finish))
                raw = "".join("data: " + json.dumps(event, separators=(",", ":")) +
                              "\n\n" for event in events) + "data: [DONE]\n\n"
                blob = raw.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
                self.wfile.flush()
            else:
                self.send_json(200, completion(body.get("model", "qwen-public-wire"),
                                               message, finish))
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": {"message": "malformed request", "type": "invalid_request_error"}})


def serve(file_path, state_path, port_file):
    server = PublicServer(("127.0.0.1", 0), file_path, state_path)
    Path(port_file).write_text(str(server.server_port))
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--port-file", required=True)
    opts = p.parse_args()
    assert Path(opts.file).is_file()
    serve(opts.file, opts.state, opts.port_file)


if __name__ == "__main__":
    main()
