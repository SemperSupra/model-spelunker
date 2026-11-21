#!/usr/bin/env python3
"""Independent fail-closed guard for aligned local Qwen/Ollama context budget."""
from pathlib import Path
import json,re
s=Path(__file__).with_name("run_context32.sh").read_text()
proxy=Path(__file__).with_name("wire_proxy.py").read_text()
def require(ok,why):
    if not ok:raise AssertionError(why)
runtime=re.search(r"export OLLAMA_CONTEXT_LENGTH=(\d+)",s)
declared=re.search(r'"contextWindowSize":(\d+)',s)
require(runtime is not None and declared is not None,"context declarations absent")
num=int(runtime.group(1))
require(num==32768 and num==int(declared.group(1)),"runtime/declared context mismatch")
require(num>20000+10000,"cannot fit source safety pad plus default margin")
require('--mode baseline' in s,"proxy must not rewrite requests")
require('requested_output_budget' in proxy and 'requested_output_budget' in s,"wire budget oracle absent")
require('hidden_fixture_oracle' in s and 'sse_tool_delta_events' in s,"actual tool oracle absent")
require('proxy-metadata.json' in s,"no redacted evidence")
require('tool_names' in s and 'read_file' in s,"tool-identity check missing")
require('OLLAMA_CONTEXT_LENGTH=16384' not in s,"old unsafe window regression")
print(json.dumps({"status":"PASS","source":"synthetic controls","aligned_context":num,"scope":"offline only"}))
