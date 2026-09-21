#!/usr/bin/env python3
from qualification.run_task import (
    engine_error_types,
    goose_inference_message_ids,
    has_engine_error_event,
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


goose_stream = """{"type":"message","message":{"id":"chatcmpl-a","role":"assistant","content":[{"type":"thinking","thinking":"x"}],"metadata":{"inference":{"provider":"ollama","requestedModel":"qwen3:1.7b"}}}}
{"type":"message","message":{"id":"chatcmpl-a","role":"assistant","content":[{"type":"thinking","thinking":"y"}],"metadata":{"inference":{"provider":"ollama","requestedModel":"qwen3:1.7b"}}}}
{"type":"message","message":{"id":"chatcmpl-b","role":"assistant","content":[{"type":"thinking","thinking":"z"}],"metadata":{"inference":{"provider":"ollama","requestedModel":"qwen3:1.7b"}}}}
"""
assert goose_inference_message_ids(goose_stream) == ["chatcmpl-a", "chatcmpl-b"]
assert goose_inference_message_ids('{"type":"message","message":{"id":"x","role":"user"}}') == []
print("PASS Goose inference stream attribution")
