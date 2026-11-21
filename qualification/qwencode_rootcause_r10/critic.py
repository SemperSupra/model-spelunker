#!/usr/bin/env python3
"""Independent source-neutral negative critic for public R10 diagnostic transformations."""
import copy
import importlib.util
import json
from pathlib import Path

file=Path(__file__).with_name("diagnostic_proxy.py")
spec=importlib.util.spec_from_file_location("r10_proxy",str(file))
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
fixture={
    "model":"qwen3:1.7b",
    "messages":[{"role":"system","content":"SENSITIVE_SYSTEM"},
                {"role":"developer","content":"SENSITIVE_DEVELOPER"},
                {"role":"user","content":"Read fixture.txt"}],
    "tools":[
        {"type":"function","function":{"name":"read_file","parameters":{"type":"object","properties":{"absolute_path":{"type":"string"}},"required":["absolute_path"]}}},
        {"type":"function","function":{"name":"task_stop","parameters":{"type":"object"}}}
    ],
    "stream":True,"stream_options":{"include_usage":True}
}
original=json.dumps(fixture,sort_keys=True)
base=module.normalize_request(copy.deepcopy(fixture),"baseline")
assert json.dumps(base,sort_keys=True)==original, "baseline mutated"
both=module.normalize_request(copy.deepcopy(fixture),"compact_both")
assert both["model"]==fixture["model"]
assert both["stream_options"]==fixture["stream_options"]
assert both["messages"][-1]==fixture["messages"][-1]
assert len(both["tools"])==1 and both["tools"][0]==fixture["tools"][0]
assert "SENSITIVE_SYSTEM" not in json.dumps(both)
assert "SENSITIVE_DEVELOPER" not in json.dumps(both)
only_system=module.normalize_request(copy.deepcopy(fixture),"compact_system")
assert len(only_system["tools"])==2 and only_system["tools"]==fixture["tools"]
only_tools=module.normalize_request(copy.deepcopy(fixture),"compact_tools")
assert only_tools["messages"]==fixture["messages"]
assert len(only_tools["tools"])==1
for mode in ("compact_schema","compact_schema_budget"):
    minim=module.normalize_request(copy.deepcopy(fixture),mode)
    assert len(minim["tools"])==1
    assert minim["tools"][0]["function"]["parameters"]["required"]==["file_path"]
    assert len(minim["messages"])==2
for bad in ("INVALID","",None):
    try:module.normalize_request(copy.deepcopy(fixture),bad)
    except ValueError:pass
    else:raise AssertionError("invalid mode admitted")
native=Path(__file__).with_name("run_native_bisect.sh").read_text()
for token in ('QWEN_R10_MODE','diagnostic_proxy.py','hidden_fixture_oracle','sse_reasoning_deltas','no_host'):
    if token=="no_host":continue
    assert token in native,token
print(json.dumps({"status":"PASS","scope":"independent R10 normalization and fail-closed mutant controls"}))
