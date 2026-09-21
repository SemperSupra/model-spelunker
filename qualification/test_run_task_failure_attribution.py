#!/usr/bin/env python3
from qualification.run_task import engine_error_types, goose_stream_provider_observations, has_engine_error_event

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
