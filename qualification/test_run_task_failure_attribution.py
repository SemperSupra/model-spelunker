#!/usr/bin/env python3
from qualification.run_task import (
    engine_error_types,
    goose_stream_provider_observations,
    has_engine_error_event,
    incremental_provider_observations,
    classify_run_outcome,
    openworker_progress_summary,
    workload_summary,
)

assert has_engine_error_event('OPENWORKER_EVENT={"type":"EventType.ERROR","error":"x"}')
assert has_engine_error_event('OPENWORKER_EVENT={"type": "EventType.ERROR", "error": "x"}')
assert not has_engine_error_event('OPENWORKER_EVENT={"type":"EventType.TOOL_RESULT"}')
print("PASS run-task engine-error attribution")

assert engine_error_types(
    'OPENWORKER_EVENT={"type":"EventType.ERROR","error_type":"ProviderError","error":"redacted"}'
) == ["ProviderError"]
assert engine_error_types(
    'OPENWORKER_EVENT={"type":"EventType.ERROR","error":"redacted"}'
) == ["unspecified"]

goose = """{"type":"message","message":{"id":"chatcmpl-a","role":"assistant","content":[{"type":"thinking","thinking":"one"}],"metadata":{"inference":{"provider":"ollama","requestedModel":"qwen3:1.7b"}}}}
{"type":"message","message":{"id":"chatcmpl-a","role":"assistant","content":[{"type":"thinking","thinking":"two"}],"metadata":{"inference":{"provider":"ollama","requestedModel":"qwen3:1.7b"}}}}
{"type":"message","message":{"id":"chatcmpl-b","role":"assistant","content":[{"type":"text","text":"next"}],"metadata":{"inference":{"provider":"ollama","requestedModel":"qwen3:1.7b"}}}}
{"type":"message","message":{"id":"user-1","role":"user","content":[{"type":"text","text":"ignore"}]}}
"""
rounds = goose_stream_provider_observations(goose)
assert len(rounds) == 2
assert rounds == [
    {"provider": "ollama", "requested_model": "qwen3:1.7b"},
    {"provider": "ollama", "requested_model": "qwen3:1.7b"},
]
print("PASS Goose stream-json turn attribution")

partial = """MODEL_SPELUNKER_MODEL_CALL_STARTED={\"index\":1,\"requested_model\":\"qwen\",\"request_message_bytes\":100,\"request_tool_schema_bytes\":20}
MODEL_SPELUNKER_MODEL_CALL_COMPLETED={\"index\":1,\"requested_model\":\"qwen\",\"request_message_bytes\":100,\"request_tool_schema_bytes\":20,\"output_text_bytes\":0,\"reasoning_bytes\":5,\"tool_argument_bytes\":12,\"client_wall_seconds\":2.5}
OPENWORKER_EVENT={\"type\":\"EventType.TOOL_STARTED\",\"name\":\"read_file\"}
OPENWORKER_EVENT={\"type\":\"EventType.TOOL_FINISHED\",\"name\":\"read_file\",\"status\":\"success\"}
MODEL_SPELUNKER_MODEL_CALL_STARTED={\"index\":2,\"requested_model\":\"qwen\",\"request_message_bytes\":200,\"request_tool_schema_bytes\":20}
"""
completed = incremental_provider_observations(partial)
assert len(completed) == 1
summary = workload_summary(completed)
assert summary["model_rounds"] == 1
assert summary["model_calls_completed"] == 1
progress = openworker_progress_summary(partial)
assert progress == {
    "tool_calls_started": 1,
    "tool_calls_completed": 1,
    "completed_tool_names": ["read_file"],
    "completed_tool_statuses": ["success"],
}
print("PASS timeout-surviving model/tool progress attribution")


# Tool-projection treatment contract is intentionally explicit and opt-in.
from pathlib import Path as _Path
_run_task_source = _Path("qualification/run_task.py").read_text(encoding="utf-8")
assert '--projected-tools-source' in _run_task_source
assert 'choices=["task", "candidate"]' in _run_task_source
assert 'projected_tools = candidate.get("toolset") or []' in _run_task_source
print("PASS opt-in configured-actor tool projection contract")


failure_class, termination = classify_run_outcome(
    success=True,
    validator_error=False,
    timed_out=False,
    candidate_exit=0,
    engine_error=False,
    iteration_censored=True,
)
assert failure_class is None
assert termination == "semantic-success"

failure_class, termination = classify_run_outcome(
    success=False,
    validator_error=False,
    timed_out=False,
    candidate_exit=0,
    engine_error=False,
    iteration_censored=True,
)
assert failure_class == "iteration-limit"
assert termination == "iteration-censored"
print("PASS success-at-iteration-boundary outcome separation")
