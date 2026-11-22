#!/usr/bin/env python3
"""Synthetic three-audience Pi RPC contract tests; never invokes a model."""
from __future__ import annotations
import base64
import json
from qualification.adapters.pi_rpc_protocol import (
    PromptObservation, parse_jsonl, prompt_record,
)

def rejects(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("unsafe RPC envelope accepted")

def main():
    message = "Describe photo \u2028 and report observations"
    image = {"type": "image", "data": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode(),
             "mimeType": "image/png"}
    human = prompt_record("same-task-1", message, [image])
    automation = prompt_record("same-task-1", message, [image])
    agent = prompt_record("same-task-1", message, [image])
    assert human == automation == agent, "audience translation changed exact task envelope"
    record = parse_jsonl(human)
    assert record["message"] == message and record["images"][0]["data"] == image["data"]

    accepted = {"id": "same-task-1", "type": "response", "command": "prompt",
                "success": True, "data": {"disposition": "started"}}
    state = PromptObservation("same-task-1")
    state.consume(accepted)
    state.consume({"type": "agent_end"})
    assert state.receipt()["agent_settled_observed"] is False
    assert state.receipt()["task_oracle_passed"] is False
    state.consume({"type": "agent_settled"})
    assert state.receipt()["agent_settled_observed"] is True
    assert state.receipt()["model_tool_qualified"] is False
    assert state.receipt()["production_admitted"] is False

    rejected = PromptObservation("same-task-1")
    rejected.consume({"id": "same-task-1", "type": "response",
                      "command": "prompt", "success": False})
    assert rejected.receipt()["prompt_accepted"] is False
    assert rejected.receipt()["task_oracle_passed"] is False

    cases = [
        lambda: prompt_record("bad id", "hello"),
        lambda: prompt_record("i", "/skill:unsafe"),
        lambda: prompt_record("i", " " * 3),
        lambda: prompt_record("i", "x" * 10000),
        lambda: prompt_record("i", "x", [{"type": "image", "data": "%%%broken",
                                        "mimeType": "image/png"}]),
        lambda: prompt_record("i", "x", [{"type": "image", "data": image["data"],
                                        "mimeType": "application/octet-stream"}]),
        lambda: prompt_record("i", "x", [image, image, image]),
        lambda: parse_jsonl(b'{"type":"response"}'),
        lambda: parse_jsonl(b'{"type":"response"}\n{"type":"prompt"}\n'),
        lambda: state.consume(accepted),
        lambda: state.consume({"id": "other", "type": "response",
                               "command": "prompt", "success": True}),
        lambda: state.consume({"type": "response", "command": "prompt", "success": True}),
    ]
    for fn in cases:
        rejects(fn)
    # Protocol-level equality is not execution equality, which remains a real harness/model oracle.
    print(json.dumps({"schema": "pi-rpc-source-contract-test/v1", "state": "PASS",
                      "negative_cases": len(cases), "audiences": 3,
                      "native_pi_process_executed": False, "task_oracle_passed": False,
                      "production_admitted": False}, sort_keys=True))

if __name__ == "__main__":
    main()
