#!/usr/bin/env python3
from qualification.run_task import engine_error_types, has_engine_error_event

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
