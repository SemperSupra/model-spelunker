#!/usr/bin/env python3
"""Independent offline negative controls for an actual Qwen+Ollama two-hop actor task."""
import json
import re
from pathlib import Path

source = Path(__file__).with_name("run_twohop.sh").read_text()
def require(condition, message):
    if not condition:
        raise AssertionError(message)

for fragment in (
    "OLLAMA_CONTEXT_LENGTH=32768",
    '"contextWindowSize":32768',
    "secrets.randbelow(2)",
    '"TARGET="+target',
    'secrets.token_hex(16)',
    'target in ("a.txt","b.txt")',
    "decoy not in stdout",
    'sse_tool_delta_events",0) for v in completed)>=2',
    'requested_output_budget",0)>=256',
    '"hidden_fixture_oracle"',
    "qualification/qwencode_twohop_r12/wire_proxy.py",
):
    require(fragment in source, "missing source control "+fragment)

def independent_verdict(target, contents, response, tool_calls, wire_budget):
    if target not in ("a.txt", "b.txt"):
        return False
    selected=contents[target]
    other=contents["b.txt" if target=="a.txt" else "a.txt"]
    return (selected in response and other not in response
            and tool_calls >= 2 and wire_budget >= 256)

files={"a.txt":"VALUE=A_N0NCE", "b.txt":"VALUE=B_N0NCE"}
for target in ("a.txt","b.txt"):
    chosen=files[target]
    other=files["b.txt" if target=="a.txt" else "a.txt"]
    require(independent_verdict(target,files,chosen,2,256),"positive failed")
    for response, count, budget in (
        (other,2,256), ("",2,256), (chosen+other,2,256),
        (chosen,1,256), (chosen,2,1), (chosen,0,1024),
    ):
        require(not independent_verdict(target,files,response,count,budget),
                "wrong-target, no-tool, or token-budget mutant admitted")
require(not independent_verdict("../private",files,"VALUE=A_N0NCE",2,256),"path mutant admitted")
print(json.dumps({"schema":"qwen-r12-two-hop-independent-oracle/v1",
                  "state":"PASS","positive_cases":2,"negative_cases":13,
                  "inference":"NOT_EXECUTED_BY_CRITIC"}))
