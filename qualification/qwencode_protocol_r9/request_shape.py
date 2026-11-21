#!/usr/bin/env python3
"""Fail-closed redacted request-shape witness; no request values are emitted."""
import argparse
import json
import sys

ALLOWED = {
    "model": str, "messages": list, "tools": list, "tool_choice": (str, dict),
    "stream": bool, "stream_options": dict, "temperature": (int, float),
    "top_p": (int, float), "max_tokens": int, "max_completion_tokens": int,
    "reasoning_effort": str, "extra_body": dict, "metadata": dict,
    "parallel_tool_calls": bool, "frequency_penalty": (int, float),
    "presence_penalty": (int, float), "seed": int, "stop": (str, list),
    "response_format": dict, "user": str, "n": int,
}

def shape(request):
    if not isinstance(request, dict):
        raise ValueError("request must be object")
    unexpected = sorted(set(request) - set(ALLOWED))
    if unexpected:
        raise ValueError("unexpected request fields: " + ",".join(unexpected))
    for key, value in request.items():
        accepted = ALLOWED[key] if isinstance(ALLOWED[key], tuple) else (ALLOWED[key],)
        if type(value) not in accepted:
            raise ValueError("invalid type: " + key)
    messages = request.get("messages", [])
    if any(not isinstance(m, dict) or not isinstance(m.get("role"), str) for m in messages):
        raise ValueError("invalid message envelope")
    tools = request.get("tools", [])
    if any(not isinstance(t, dict) or t.get("type") != "function" for t in tools):
        raise ValueError("invalid tool envelope")
    so = request.get("stream_options", {})
    if set(so) - {"include_usage"} or ("include_usage" in so and type(so["include_usage"]) is not bool):
        raise ValueError("invalid stream_options")
    return {"fields": {k: type(v).__name__ for k, v in sorted(request.items())},
            "message_roles": [m["role"] for m in messages],
            "tool_count": len(tools), "stream_include_usage": so.get("include_usage", None)}

def selftest(mode):
    req = {"model": "synthetic", "messages": [{"role": "user", "content": "TOP_SECRET"}],
           "tools": [{"type": "function", "function": {"name": "read_file",
                       "parameters": {"secret": "SENSITIVE"}}}],
           "stream": True, "stream_options": {"include_usage": True}}
    out = shape(req)
    assert "TOP_SECRET" not in json.dumps(out) and "SENSITIVE" not in json.dumps(out)
    assert out["stream_include_usage"] is True and out["tool_count"] == 1
    if mode == "negative":
        for mutant in [dict(req, api_key="SENSITIVE"),
                       dict(req, stream_options={"unexpected": "x"}),
                       dict(req, messages="SENSITIVE"),
                       dict(req, tools=[{"type": "unknown"}])]:
            try:
                shape(mutant)
            except ValueError:
                pass
            else:
                raise AssertionError("negative mutant falsely accepted")
    print(json.dumps({"test": mode, "status": "PASS",
                      "scope": "synthetic request metadata only"}))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", choices=["positive", "negative"])
    args = parser.parse_args()
    try:
        if args.selftest:
            selftest(args.selftest)
        else:
            print(json.dumps(shape(json.load(sys.stdin)), sort_keys=True))
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "REJECT", "reason": str(exc)}), file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
