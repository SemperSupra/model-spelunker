#!/usr/bin/env python3
"""Test-only candidate used to prove the qualification runner contract."""

from pathlib import Path

Path("value.txt").write_text("READY\n", encoding="utf-8")
print('MODEL_SPELUNKER_USAGE={"input":11,"output":3,"cache_read":2,"cache_write":0}')
print("MODEL_SPELUNKER_TOOL_CALLS=1")
