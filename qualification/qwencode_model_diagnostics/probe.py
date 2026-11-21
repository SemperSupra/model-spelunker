#!/usr/bin/env python3
"""Public-only, stdlib direct Ollama OpenAI tool-SSE diagnosis.

No Qwen CLI, no private endpoint, no credential, no private input. This script
isolates direct model-provider/tool selection and streamed tool delta shape.
It never treats a tool call as proof of tool execution.
"""
import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


def parse_stream(raw):
    """Extract OpenAI-compatible SSE tool-call chunks; supports split deltas."""
    acc = {}
    final_reason = None
    deltas = 0
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        body = line[6:]
        if body == "[DONE]":
            break
        msg = json.loads(body)
        for choice in msg.get("choices", []):
            deltas += 1
            if choice.get("finish_reason"):
                final_reason = choice["finish_reason"]
            delta = choice.get("delta") or {}
            for call in delta.get("tool_calls") or []:
                index = call.get("index")
                if not isinstance(index, int) or index < 0 or index > 8:
                    continue
                item = acc.setdefault(index, {"name": "", "arguments": ""})
                fn = call.get("function") or {}
                item["name"] += str(fn.get("name") or "")
                item["arguments"] += str(fn.get("arguments") or "")
    return list(acc.values()), final_reason, deltas


def parse_nonstream(raw):
    msg = json.loads(raw)
    calls = []
    final_reason = None
    for choice in msg.get("choices", []):
        final_reason = choice.get("finish_reason")
        for call in (choice.get("message") or {}).get("tool_calls") or []:
            fn = call.get("function") or {}
            args = fn.get("arguments") or ""
            calls.append({"name": str(fn.get("name") or ""),
                          "arguments": args if isinstance(args, str) else json.dumps(args)})
    return calls, final_reason


def valid_tool(calls):
    for call in calls:
        if call.get("name") != "read_file":
            continue
        try:
            args = json.loads(call.get("arguments") or "{}")
        except (ValueError, TypeError):
            continue
        if isinstance(args, dict) and args.get("file_path") == "fixture.txt":
            return True
    return False


def request_payload(stream):
    return {
        "model": "qwen3:1.7b",
        "messages": [{
            "role": "user",
            "content": "Call the read_file tool with file_path exactly fixture.txt. Do not claim to have read it until the tool returns."
        }],
        "tools": [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read one text file in the bounded synthetic workspace",
                "parameters": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"]
                }
            }
        }],
        "tool_choice": "auto",
        "stream": stream,
        "reasoning_effort": "none",
        "temperature": 0,
        "max_tokens": 256
    }


def one_rep(url, stream):
    payload = json.dumps(request_payload(stream)).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json",
                                    "Authorization": "Bearer ollama"},
        method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=100) as resp:
            raw = resp.read(3_000_000)
            duration = time.monotonic() - started
        if stream:
            calls, reason, delta_count = parse_stream(raw.decode())
        else:
            calls, reason = parse_nonstream(raw.decode())
            delta_count = None
        passed = valid_tool(calls)
        return {
            "stream": stream, "result": "PASS" if passed else "FAIL",
            "http_status": 200, "elapsed_seconds": round(duration, 2),
            "tool_calls_present": len(calls) > 0,
            "target_tool_call_valid": passed,
            "finish_reason": str(reason),
            "stream_choice_deltas": delta_count,
            "raw_response_content": "NOT_RETAINED"
        }
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as e:
        return {
            "stream": stream, "result": "FAIL",
            "failure_type": type(e).__name__,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "raw_response_content": "NOT_RETAINED"
        }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:11434/v1/chat/completions")
    p.add_argument("--receipt", type=Path, required=True)
    args = p.parse_args()
    if args.url != "http://127.0.0.1:11434/v1/chat/completions":
        raise SystemExit("ONLY_EXACT_LOOPBACK_OLLAMA_ROUTE_ALLOWED")
    rows = [one_rep(args.url, False), one_rep(args.url, True)]
    verdict = "PASS" if all(r["result"] == "PASS" for r in rows) else "FAIL"
    doc = {
        "schema": "qwen-public-ollama-wire-diagnostic/v1",
        "verdict": verdict,
        "runtime": "PUBLIC_GHA_CPU_ONLY",
        "provider": "OLLAMA_LOOPBACK_QWEN3_1P7B",
        "reasoning": "none",
        "endpoint_egress": "LOCAL_LOOPBACK_ONLY",
        "qwen_cli_agent": "NOT_TESTED_IN_THIS_BAND",
        "synthetic_tool_executed": "NOT_TESTED",
        "sovereign_provider": "NOT_TESTED",
        "cases": rows
    }
    args.receipt.write_text(json.dumps(doc,sort_keys=True,indent=2)+"\n")
    print(json.dumps(doc,sort_keys=True))
    if verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
