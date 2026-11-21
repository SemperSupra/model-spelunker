#!/usr/bin/env python3
"""R34 three-audience evidence contract. Stdlib-only, source-safe, no side effects.

This contract is an observation record, NOT an actor registry or admission.
No feature is assumed native simply because an agent has an MCP client.
"""
from __future__ import annotations
import copy
import json
import re
import sys
from pathlib import Path

AUDIENCES = ("human", "automation", "agent")
STATES = ("NATIVE", "ADAPTER_VERIFIED", "UNVERIFIED", "UNSUPPORTED", "HOLD")
INTERFACES = {
    "human": {"terminal", "web", "touch", "voice", "camera", "photo"},
    "automation": {"cli", "structured-output", "session-api", "events"},
    "agent": {"mcp-server", "acp", "typed-api", "cli-adapter"},
}
ENVIRONMENTS = {"windows-amd64", "linux-amd64", "linux-arm64", "macos-arm64",
                "android-arm64", "ios-browser"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
# No production targets, URLs, credentials or implementation-specific paths in public records.
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")

def fail(message: str):
    raise ValueError(message)

def check(record: dict) -> dict:
    if not isinstance(record, dict) or set(record) != {
        "schema", "harness", "source", "target", "audiences", "gates"}:
        fail("unknown or missing top-level fields")
    if record["schema"] != "agent-three-audience-observation/v1":
        fail("unexpected schema")
    if not isinstance(record["harness"], str) or not SAFE_NAME.fullmatch(record["harness"]):
        fail("unsafe harness id")
    source = record["source"]
    if not isinstance(source, dict) or set(source) != {"commit", "version", "legacy_retained"}:
        fail("unknown source fields")
    if not isinstance(source["commit"], str) or not HEX40.fullmatch(source["commit"]):
        fail("unverified upstream source identity")
    if not isinstance(source["version"], str) or not SAFE_NAME.fullmatch(source["version"]):
        fail("unsafe version")
    if source["legacy_retained"] is not True:
        fail("comparison baseline must be retained")
    if record["target"] not in ENVIRONMENTS:
        fail("unknown target environment")
    gates = record["gates"]
    if not isinstance(gates, dict) or set(gates) != {
        "source_checked", "execution_verified", "task_oracle_passed",
        "physical_target_verified", "production_admitted"}:
        fail("unknown evidence gates")
    if any(type(v) is not bool for v in gates.values()):
        fail("gate values must be explicit booleans")
    if gates["production_admitted"]:
        fail("public observation never grants production authority")
    if gates["task_oracle_passed"] and not gates["execution_verified"]:
        fail("task pass without executing actor")
    if gates["physical_target_verified"] and not gates["execution_verified"]:
        fail("physical target proof without actor execution")
    if not isinstance(record["audiences"], dict) or set(record["audiences"]) != set(AUDIENCES):
        fail("three-audience assessment required")
    observed = 0
    for audience, allowed in INTERFACES.items():
        entries = record["audiences"][audience]
        if not isinstance(entries, list) or not entries:
            fail("audience must declare at least one interface")
        names = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "interface", "status", "origin", "source_ref", "receipt_sha256"}:
                fail("unknown interface evidence fields")
            iface, status = entry["interface"], entry["status"]
            if iface not in allowed or iface in names or status not in STATES:
                fail("invalid or duplicate interface/status")
            names.add(iface)
            origin = entry["origin"]
            if origin not in ("upstream", "adapter", "none"):
                fail("invalid provenance origin")
            ref, digest = entry["source_ref"], entry["receipt_sha256"]
            if ref is not None and (not isinstance(ref, str) or
                                    not re.fullmatch(r"[A-Za-z0-9._/-]{1,160}", ref) or
                                    ".." in Path(ref).parts or ref.startswith("/")):
                fail("unsafe source reference")
            if digest is not None and (not isinstance(digest, str) or
                                       not HEX64.fullmatch(digest)):
                fail("bad oracle receipt sha256")
            if status == "NATIVE" and (origin != "upstream" or ref is None or not gates["source_checked"]):
                fail("native capability needs pinned upstream source verification")
            if status == "ADAPTER_VERIFIED" and (origin != "adapter" or
                 ref is None or digest is None or not gates["execution_verified"]):
                fail("adapter capability needs independent executable receipt")
            if status in ("UNVERIFIED", "UNSUPPORTED", "HOLD") and digest is not None:
                fail("non-admitted status cannot claim an executable receipt")
            if iface == "mcp-server" and status == "NATIVE" and origin != "upstream":
                fail("MCP client or adapter is not a native MCP server")
            if status in ("NATIVE", "ADAPTER_VERIFIED"):
                observed += 1
    return {"schema": "agent-three-audience-critic/v1",
            "state": "SOURCE_CONTRACT_VALID",
            "harness": record["harness"], "target": record["target"],
            "verified_surface_count": observed,
            "actor_task_qualified": bool(gates["task_oracle_passed"]),
            "production_admission": "NOT_GRANTED"}

def self_test():
    example = Path(__file__).with_name("three_audience_example.json")
    datum = json.loads(example.read_text(encoding="utf-8"))
    assert check(datum)["production_admission"] == "NOT_GRANTED"
    mutations = [
        lambda x: x["gates"].update(production_admitted=True),
        lambda x: x["gates"].update(task_oracle_passed=True),
        lambda x: x["source"].update(commit="latest"),
        lambda x: x["source"].update(legacy_retained=False),
        lambda x: x["audiences"].pop("agent"),
        lambda x: x["audiences"]["agent"][0].update(status="NATIVE"),
        lambda x: x["audiences"]["agent"][0].update(status="ADAPTER_VERIFIED"),
        lambda x: x["audiences"]["agent"][0].update(receipt_sha256="0"*64),
        lambda x: x["audiences"]["human"][0].update(interface="mcp-server"),
        lambda x: x["audiences"]["automation"][0].update(origin="adapter"),
        lambda x: x.update(target="jetson-gpu-proven"),
        lambda x: x["gates"].update(source_checked="yes"),
    ]
    for i, mutate in enumerate(mutations):
        bad = copy.deepcopy(datum)
        mutate(bad)
        try:
            check(bad)
        except (ValueError, KeyError, TypeError):
            pass
        else:
            raise AssertionError("unsafe mutation accepted: " + str(i))
    print(json.dumps({"schema": "agent-three-audience-self-test/v1",
                      "state": "PASS", "negative_controls": len(mutations),
                      "runtime_effect": False, "network": False}, sort_keys=True))

if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "self-test":
        self_test()
    elif len(sys.argv) == 2:
        print(json.dumps(check(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))),
                         sort_keys=True))
    else:
        raise SystemExit("usage: audience_contract.py self-test|observation.json")
