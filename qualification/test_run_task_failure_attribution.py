#!/usr/bin/env python3
from qualification.run_task import engine_error_types, goose_stream_provider_observations, has_engine_error_event, tool_action_summary, workload_summary, tool_action_summary

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

# Distinguish model stop-without-tool from provider-declared tool calling;
# never echo raw assistant text or accept arbitrary provider strings as labels.
observed = workload_summary([
    {"finish_reason": "stop", "tool_argument_bytes": 0, "output_text_bytes": 309},
    {"finish_reason": "tool_calls", "tool_argument_bytes": 44},
    {"finish_reason": "free-form-untrusted-raw-output"},
])
assert observed["provider_finish_reason_counts"] == {"stop": 1, "tool_calls": 1}
assert observed["provider_finish_reason_unknown_count"] == 1
assert observed["tool_argument_bytes_total"] == 44.0
assert "free-form-untrusted-raw-output" not in str(observed)
assert "raw" not in observed
assert "provider_finish_reason_counts" not in workload_summary([{}])
print("PASS provider finish-reason tool-protocol attribution")

sample = {
    "tool_calls":["list_files","read_file","read_file","write_file","arbitrary_unknown_tool"],
    "approvals":[
        {"tool_name":"write_file","path":"/private/absolute/path","allowed":True},
        {"tool_name":"write_file","path":"secret.txt","allowed":False},
        {"tool_name":"read_file","path":"private","allowed":False},
    ],
}
import json
safe = tool_action_summary("prefix\nOPENWORKER_SUMMARY="+json.dumps(sample)+"\n")
assert safe["tool_name_counts"] == {"list_files":1,"read_file":2,"write_file":1}
assert safe["unknown_tool_name_count"] == 1
assert safe["write_approvals_granted"] == 1
assert safe["write_approvals_denied"] == 1
assert "secret.txt" not in str(safe)
assert "/private/" not in str(safe)
assert tool_action_summary("OPENWORKER_SUMMARY={invalid}") == {}
assert tool_action_summary("") == {}
print("PASS bounded tool-name and approval telemetry")

# The native adapter emits an explicit, observed configuration cap. Only the
# allowlisted integer is projected; arbitrary summary paths/text stay private.
good='OPENWORKER_SUMMARY={"tool_calls":["list_files","read_file"],"max_iterations":8,"approvals":[],"host_secret":"NO_LEAK"}'
projected=tool_action_summary(good)
assert projected["configured_max_iterations"]==8
assert projected["tool_name_counts"]["read_file"]==1
assert "host_secret" not in str(projected)
for raw in ('"8"', '0', '13', 'null', 'true'):
    bad='OPENWORKER_SUMMARY={"tool_calls":[],"max_iterations":'+raw+'}'
    assert "configured_max_iterations" not in tool_action_summary(bad)
print("PASS bounded observed max-iteration projection")
