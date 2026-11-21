#!/usr/bin/env python3
"""Fail-closed synthetic OpenAI SSE metadata oracle; never print model content."""
import argparse
import json
import sys

def classify(events):
    if not isinstance(events, list) or not events:
        raise ValueError("expected nonempty event array")
    result = {"chunks": 0, "usage_only": 0, "content": 0, "reasoning": 0,
              "tool_deltas": 0, "finish_reasons": [], "tool_indices": []}
    indices = set()
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("choices"), list):
            raise ValueError("malformed event")
        result["chunks"] += 1
        if not event["choices"]:
            if not isinstance(event.get("usage"), dict):
                raise ValueError("empty choices without usage")
            result["usage_only"] += 1
            continue
        for choice in event["choices"]:
            if not isinstance(choice, dict) or not isinstance(choice.get("delta"), dict):
                raise ValueError("malformed choice")
            delta = choice["delta"]
            if "role" in delta and delta["role"] not in ("assistant", "tool"):
                raise ValueError("invalid role")
            for field, label in (("content", "content"),
                                 ("reasoning", "reasoning"),
                                 ("reasoning_content", "reasoning")):
                value = delta.get(field)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError("invalid text field")
                    if value:
                        result[label] += 1
            if "tool_calls" in delta:
                if not isinstance(delta["tool_calls"], list):
                    raise ValueError("invalid tool calls")
                for tool in delta["tool_calls"]:
                    if not isinstance(tool, dict) or type(tool.get("index")) is not int or tool["index"] < 0:
                        raise ValueError("invalid tool index")
                    indices.add(tool["index"])
                    result["tool_deltas"] += 1
            finish = choice.get("finish_reason")
            if finish is not None:
                if finish not in ("stop", "length", "tool_calls", "content_filter", "function_call"):
                    raise ValueError("invalid finish reason")
                result["finish_reasons"].append(finish)
    result["tool_indices"] = sorted(indices)
    result["outcome"] = ("TOOL_PROGRESS" if result["tool_deltas"] else
                         "CONTENT_PROGRESS" if result["content"] else
                         "REASONING_ONLY" if result["reasoning"] else "NO_VISIBLE_RESPONSE")
    return result

def selftest(kind):
    def chunk(delta, finish=None):
        return {"choices": [{"delta": delta, "finish_reason": finish}]}
    trailer = {"choices": [], "usage": {"total_tokens": 12}}
    if kind == "positive":
        cases = [
            ([chunk({"content": "SENSITIVE"}), chunk({}, "stop"), trailer], "CONTENT_PROGRESS"),
            ([chunk({"tool_calls": [{"index": 0, "function": {"arguments": "SENSITIVE"}}]}),
              chunk({}, "tool_calls"), trailer], "TOOL_PROGRESS"),
            ([chunk({"reasoning_content": "SENSITIVE"}), chunk({}, "stop"), trailer], "REASONING_ONLY"),
            ([chunk({"role": "assistant"}), chunk({}, "stop"), trailer], "NO_VISIBLE_RESPONSE"),
        ]
        for events, expected in cases:
            actual = classify(events)
            assert actual["outcome"] == expected and actual["usage_only"] == 1
            assert "SENSITIVE" not in json.dumps(actual)
    else:
        bad = [[], [{}], [{"choices": []}], [chunk({"role": "system"})],
               [chunk({"content": {"secret": "SENSITIVE"}})],
               [chunk({"tool_calls": [{"index": -1}]})], [chunk({}, "mystery")]]
        for events in bad:
            try:
                classify(events)
            except ValueError:
                continue
            raise AssertionError("negative mutant accepted")
    print(json.dumps({"status": "PASS", "test": kind, "scope": "synthetic SSE only"}))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", choices=("positive", "negative"))
    opt = p.parse_args()
    try:
        if opt.selftest:
            selftest(opt.selftest)
        else:
            print(json.dumps(classify(json.load(sys.stdin)), sort_keys=True))
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "REJECT", "reason": str(exc)}), file=sys.stderr)
        sys.exit(2)
