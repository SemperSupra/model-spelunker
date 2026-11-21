#!/usr/bin/env python3
"""Independent, stdlib, fail-closed source-only agent workcell profile validator."""
from __future__ import annotations
import copy
import json
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parent
VALID_ROUTES={"ollama-openai-loopback","llama-server-openai-loopback","governed-proxy"}
VALID_IDS={"qwen-code","goose","codex-exec","openworker"}
VALID_TARGETS={"public-linux-amd64","public-windows-amd64","sovereign-linux-amd64",
               "sovereign-macos-arm64","windows-hyperv-guest-amd64"}
LOCAL={"http://127.0.0.1:11434/v1","http://127.0.0.1:8080/v1"}
def reject(message:str):
    raise ValueError(message)
def check(x:dict)->dict:
    if x.get("schema")!="agent-fleet-runtime-targets/v1" or x.get("status")!="DESIGN_CONTRACT_NOT_DEPLOYED":
        reject("false source/promotion state")
    a=x["authority"];c=x["common"]
    if a["self_authorization"] is not False or a["production_admitted"] is not False:
        reject("self-authority forbidden")
    if a["max_delegation_depth"]!=0 or c["global_approval_bypass"] is not False or c["auto_model_upgrade"] is not False:
        reject("unbounded agent/config upgrades forbidden")
    if c["memory_default"]!="disabled" or c["mcp_default"]!="disabled" or a["secret_source"]!="scoped_runtime_injection_not_git":
        reject("unauthorized memory/MCP/secret handling")
    if c["artifact"]!="immutable_oci_digest" or a["workspace_mutation"]!="explicit_task_scope_only":
        reject("missing artifact/workcell boundary")
    routes=x["routes"];targets=x["targets"];harnesses=x["harnesses"]
    if {r["id"] for r in routes}!=VALID_ROUTES:reject("route inventory drift")
    if {t["id"] for t in targets}!=VALID_TARGETS:reject("substrate inventory drift")
    if {h["id"] for h in harnesses}!=VALID_IDS:reject("harness inventory drift")
    for route in routes:
        rid=route["id"]
        if route["type"]!="openai-compatible":reject("unsupported route transport")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}",route["credential_env"]):
            reject("secret value or invalid env reference")
        if rid!="governed-proxy":
            if route["url"] not in LOCAL or route["admission"]!="LOOPBACK_ISOLATED_WORKCELL_ONLY":
                reject("unknown network route or implied private endpoint")
        else:
            if route["url"] is not None or route["url_env"]!="ADMITTED_MODEL_BASE_URL" or route["admission"]!="EXTERNAL_SIGNED_SCOPE_REQUIRED":
                reject("governed proxy must be externally admitted")
    for target in targets:
        if set(target["allowed_routes"])-VALID_ROUTES or not target["allowed_routes"]:
            reject("unsupported runtime route")
        if target["environment"]=="public-free-ci":
            if target["controller"]!="GHA_SYNTHETIC_ONLY" or "governed-proxy" in target["allowed_routes"]:
                reject("unsafe public cloud authority")
        else:
            if target["controller"]!="EXTERNAL_CONTROLLER_ADMISSION_REQUIRED" or target["model_inference"]!="not_observed_in_this_contract":
                reject("false private-host admission claim")
        if target["os"]=="windows" and not target["runtime"].startswith("powershell-5.1"):
            reject("Windows 5.1 runtime constraint")
    for h in harnesses:
        if h["refresh_version"]!="PENDING_UPSTREAM_SOURCE_CENSUS" or h["config_status"]!="SOURCE_BASELINE_ONLY":
            reject("unverified current version/promoted configuration")
        if h["default_model"]!="qwen3:1.7b" or h["default_context"]!=32768:
            reject("unproven default model or context")
        if h["max_tool_rounds"]<1 or h["max_tool_rounds"]>4:
            reject("unbounded agent/tool budget")
        if h["default_output_tokens"]!=256 or not h["write_requires"]:
            reject("unbounded output/write authority")
        if h["id"]=="qwen-code" and h["tools"]!=["read_file"]:
            reject("Qwen configured tool surface changed without qualification")
        if h["id"]=="codex-exec" and h["write_requires"]!="task_scoped_workcell_with_explicit_admission":
            reject("Codex shell authority not explicitly bound")
    return {"schema":"agent-fleet-runtime-profiles-critic/v1","state":"SOURCE_ONLY_VALIDATED",
            "targets":len(targets),"harnesses":len(harnesses),
            "runtime_qualification":"NOT_PERFORMED","production_admission":"NOT_GRANTED"}
def test():
    doc=json.loads((ROOT/"runtime_targets.json").read_text())
    assert check(doc)["targets"]==5
    mutants=[
        ("self-authorize",lambda d:d["authority"].update(self_authorization=True)),
        ("production",lambda d:d["authority"].update(production_admitted=True)),
        ("yo-lo",lambda d:d["common"].update(global_approval_bypass=True)),
        ("auto-upgrade",lambda d:d["common"].update(auto_model_upgrade=True)),
        ("memory",lambda d:d["common"].update(memory_default="sync")),
        ("mcp",lambda d:d["common"].update(mcp_default="all")),
        ("private-ip",lambda d:d["routes"][0].update(url="http://192.168.1.3:11434/v1")),
        ("proxy-bypass",lambda d:d["routes"][2].update(url="http://127.0.0.1:3333/v1")),
        ("public-proxy",lambda d:d["targets"][0]["allowed_routes"].append("governed-proxy")),
        ("production-host",lambda d:d["targets"][2].update(controller="GHA_SYNTHETIC_ONLY")),
        ("windows-ps7",lambda d:d["targets"][1].update(runtime="powershell-7")),
        ("unqualified-model",lambda d:d["harnesses"][0].update(default_model="qwen3:32b")),
        ("wrong-context",lambda d:d["harnesses"][0].update(default_context=2048)),
        ("shell-unadmitted",lambda d:d["harnesses"][2].update(write_requires="none")),
        ("tool-overreach",lambda d:d["harnesses"][0].update(tools=["run_shell_command"])),
        ("unsupported-latest",lambda d:d["harnesses"][1].update(refresh_version="latest"))
    ]
    for name,change in mutants:
        modified=copy.deepcopy(doc);change(modified)
        try:check(modified)
        except (ValueError,AssertionError,KeyError,TypeError):
            continue
        raise AssertionError("unsafe runtime contract mutant accepted: "+name)
    print(json.dumps({**check(doc),"negative_mutants_rejected":len(mutants)},sort_keys=True))
if __name__=="__main__":test()
