#!/usr/bin/env python3
"""Exact-source, non-executing model/runtime settings projections for harness fleet.

This module emits data-only capability and config *candidates*. It does not
claim that a runtime accepts a setting until an isolated native integration
test proves it. No host discovery, state mutation, network or secret values.
"""
from __future__ import annotations
import copy
import json
import re
from pathlib import Path

SOURCE={
 "goose":{"version":"1.60.2","commit":"fb55b5a6d7f5b5df96c8f817f1cde6a81880d9f1",
  "code":"crates/goose/src/providers/ollama_def.rs"},
 "codex-exec":{"version":"0.171.0","commit":"ccf9be8cc458bd6b8336fe84d68d8893f2691a5e",
  "code":"codex-rs/exec/src/lib.rs"},
 "openworker":{"version":"0.3.4","commit":"d1b8cd69ceccb10e75bb58ea133a5cf7cb981b89",
  "code":"coworker/config.py"},
 "qwen-code":{"version":"0.28.3","commit":"99fcf89892f1a3a8027c75468546c7e7be906245",
  "code":"packages/cli/src/config/settingsSchema.ts"}
}
MODEL="qwen3:1.7b"
def plan(harness:str,route:str,workcell_root:str="/synthetic/workcell")->dict:
    if harness not in SOURCE:raise ValueError("unrecognized harness")
    if route not in ("ollama-loopback","llama-server-loopback","external-admitted"):
        raise ValueError("unapproved model route")
    if not re.fullmatch(r"/[A-Za-z0-9._/-]{4,128}",workcell_root) or ".." in Path(workcell_root).parts:
        raise ValueError("untrusted workcell path")
    if route=="external-admitted":
        # No concrete host address, no self-authorized endpoint. An external
        # owner-controlled workcell must resolve an admitted route at runtime.
        base=None
    else:
        base="http://127.0.0.1:11434" if route=="ollama-loopback" else "http://127.0.0.1:8080"
    result={"schema":"agent-fleet-harness-native-config-candidate/v1",
        "harness":harness,"harness_version":SOURCE[harness]["version"],
        "upstream_commit":SOURCE[harness]["commit"],
        "upstream_source_file":SOURCE[harness]["code"],
        "model":MODEL,"route_kind":route,
        "observed_runtime_route":False,"task_qualified":False,
        "production_admitted":False,"apply_performed":False,
        "requires_external_workcell_lease":True,
        "permission_mode":"task-scoped-deny-by-default",
        "memory":"disabled","mcp":"disabled","unbounded_approval":False,
        "context_tokens":32768,"max_output_tokens":256,
        "config_projection":{},"caveats":[]}
    cfg=result["config_projection"]
    if harness=="goose":
        if route=="llama-server-loopback":
            result["caveats"].append("Goose native Ollama provider not established for llama-server; alternative provider requires independent qualification")
        cfg.update({
            "GOOSE_PROVIDER":"ollama",
            "GOOSE_MODEL":MODEL,
            "OLLAMA_HOST":base if route=="ollama-loopback" else None,
            "OLLAMA_TIMEOUT":120,
            "OLLAMA_STREAM_TIMEOUT":120,
            "OLLAMA_STREAM_USAGE":False,
            "GOOSE_INPUT_LIMIT":32768,
            "GOOSE_MAX_TURNS":4})
        result["caveats"].append("Goose OLLAMA_HOST is native Ollama root URL, NOT OpenAI /v1; max turns key remains qualification-runner limit, not proven upstream env config")
        # Neither GOOSE_MAX_TURNS nor GOOSE_INPUT_LIMIT is proven a context-window
        # setting; explicit tool budget must be enforced by a separate runner.
        cfg.pop("GOOSE_MAX_TURNS")
    elif harness=="codex-exec":
        cfg.update({"cli_switches":["--oss","--local-provider","ollama","-m",MODEL],
            "model_explicit":True,
            "sandbox":"workspace-write-only-after-external-task-admission",
            "interactive_approval":"not-authorized-in-autonomous-workcell",
            "model_endpoint":"INDEPENDENT_PROJECTION_REQUIRED"})
        result["caveats"].append("Codex OSS mode defaults to gpt-oss:20b if model not specified; exact -m avoids implicit model selection but may trigger provider model readiness; no live run authorized")
        if route!="ollama-loopback":result["caveats"].append("Codex non-Ollama route requires independently source-verified provider configuration")
    elif harness=="openworker":
        cfg.update({
            "COWORKER_STATE_DIR":workcell_root+"/state",
            "COWORKER_MAX_OUTPUT_TOKENS":"256",
            "COWORKER_TOOL_RESULT_MAX_BYTES":"8192",
            "COWORKER_COMPACTION_CAP_TOKENS":"24000",
            "COWORKER_COMPACTION_SUMMARY_MAX_TOKENS":"1024",
            "model":MODEL,
            "workspace_trusted":False,
            "allowed_commands":[],
            "auto_allow":[],
            "allowed_domains":[]})
        result["caveats"].append("State dir is workcell-local; provider/model compatibility and exact config.toml serializer require native acceptance; no implicit default gpt-5.6-sol")
        result["caveats"].append("Workspace override cannot widen machine sandbox/auto_allow/allowed_domains; application trust model not an authorization proof")
    else:
        cfg.update({
            "profile":"qualification/agent_embodiment/qwen-public-linux.json",
            "model":MODEL,"tools":["read_file"],"mcp_servers":{},
            "team_memory":False})
        result["caveats"].append("Existing Qwen v0.28.3 baseline is current; do not modify pinned runtime profile without an independent exact native task trial")
    if route=="external-admitted":
        cfg["admitted_route_env"]="ADMITTED_MODEL_BASE_URL"
        cfg["admitted_credential_env"]="ADMITTED_MODEL_API_KEY"
        result["caveats"].append("Runtime must independently validate external lease, endpoint and scoped credentials; no env reference grants authority")
    return result

def validate(x:dict)->None:
    if x.get("schema")!="agent-fleet-harness-native-config-candidate/v1":
        raise ValueError("bad config schema")
    if x.get("harness") not in SOURCE or x.get("upstream_commit")!=SOURCE[x["harness"]]["commit"]:
        raise ValueError("framework source drift")
    if x.get("production_admitted") is not False or x.get("apply_performed") is not False or x.get("task_qualified") is not False:
        raise ValueError("false operational admission")
    if x.get("unbounded_approval") is not False or not x.get("requires_external_workcell_lease"):
        raise ValueError("ambient agent authority")
    if x.get("memory")!="disabled" or x.get("mcp")!="disabled":
        raise ValueError("unapproved agent capability")
    if x.get("context_tokens")!=32768 or x.get("max_output_tokens")!=256:
        raise ValueError("unsupported model envelope")
    cfg=x.get("config_projection")
    if not isinstance(cfg,dict):raise ValueError("invalid config projection")
    if any(k.upper().endswith(("TOKEN","PASSWORD","SECRET")) for k in cfg):
        raise ValueError("credential values must not be recorded")
    if x.get("harness")=="goose":
        if cfg.get("GOOSE_PROVIDER")!="ollama" or cfg.get("GOOSE_MODEL")!=MODEL:raise ValueError("Goose model drift")
        if cfg.get("OLLAMA_HOST") not in (None,"http://127.0.0.1:11434"):
            raise ValueError("Goose native root must not use /v1")
        if cfg.get("OLLAMA_STREAM_USAGE") is not False:
            raise ValueError("Goose stream use not controlled")
    if x.get("harness")=="codex-exec":
        args=cfg.get("cli_switches",[])
        if args!=["--oss","--local-provider","ollama","-m",MODEL]:
            raise ValueError("Codex explicit model/provider required")
        if cfg.get("sandbox")!="workspace-write-only-after-external-task-admission":
            raise ValueError("Codex unadmitted filesystem authority")
    if x.get("harness")=="openworker":
        if cfg.get("workspace_trusted") is not False or cfg.get("auto_allow")!=[] or cfg.get("allowed_domains")!=[]:
            raise ValueError("OpenWorker unsafe workspace trust")
        if not str(cfg.get("COWORKER_STATE_DIR","")).startswith("/synthetic/workcell/"):
            raise ValueError("OpenWorker persistent or escaped state path")
    if x.get("harness")=="qwen-code":
        if cfg.get("tools")!=["read_file"] or cfg.get("mcp_servers")!={}:
            raise ValueError("Qwen tool escalation")
def selftest():
    cases=[plan(name,"ollama-loopback") for name in SOURCE]
    for x in cases:validate(x)
    for x in cases:
        for key,val in (("production_admitted",True),("task_qualified",True),
                        ("apply_performed",True),("memory","on"),("unbounded_approval",True)):
            bad=copy.deepcopy(x);bad[key]=val
            try:validate(bad)
            except ValueError:pass
            else:raise AssertionError("unadmitted field accepted "+key)
    mutations=[
       ("goose",lambda c:c.update(OLLAMA_HOST="http://127.0.0.1:11434/v1")),
       ("goose",lambda c:c.update(OLLAMA_STREAM_USAGE=True)),
       ("codex-exec",lambda c:c.update(cli_switches=["--oss"])),
       ("codex-exec",lambda c:c.update(sandbox="danger-full-access")),
       ("openworker",lambda c:c.update(workspace_trusted=True)),
       ("openworker",lambda c:c.update(auto_allow=["*"])),
       ("qwen-code",lambda c:c.update(tools=["shell"])),
       ("qwen-code",lambda c:c.update(mcp_servers={"all":{}})),
    ]
    for name,change in mutations:
        bad=plan(name,"ollama-loopback");change(bad["config_projection"])
        try:validate(bad)
        except ValueError:pass
        else:raise AssertionError("unsafe native config accepted: "+name)
    print(json.dumps({"schema":"agent-fleet-harness-native-config-critic/v1",
        "state":"PASS","harnesses":len(cases),
        "negative_field_mutants":5*len(cases),"negative_harness_mutants":len(mutations),
        "native_config_applied":False,"model_inference":False,"production_admission":"NOT_GRANTED"},sort_keys=True))
if __name__=="__main__":selftest()
