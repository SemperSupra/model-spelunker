#!/usr/bin/env python3
"""Test-only candidate used to prove the qualification runner contract."""

from pathlib import Path

Path("value.txt").write_text("READY\n", encoding="utf-8")
print('MODEL_SPELUNKER_USAGE={"input":11,"output":3,"cache_read":2,"cache_write":0}')
print("MODEL_SPELUNKER_TOOL_CALLS=1")

print('MODEL_SPELUNKER_PROVIDER_OBSERVATIONS=[{"requested_model":"contract-test","resolved_model":"contract-test","request_message_bytes":100,"request_tool_schema_bytes":25,"output_text_bytes":5,"reasoning_bytes":0,"tool_argument_bytes":12,"client_wall_seconds":0.25,"first_event_seconds":0.05,"prompt_tokens":11,"completion_tokens":3}]')
