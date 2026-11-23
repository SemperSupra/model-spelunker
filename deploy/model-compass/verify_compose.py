#!/usr/bin/env python3
"""Public-safe structured lint for normalized native Compose IR.

This is a source/IR test only; it does not implement Foundry lifecycle, render an
official TrueNAS app or grant runtime target qualification.
"""
import json
import pathlib
import sys

def require(cond, reason):
    if not cond:
        raise SystemExit("REFUSE: " + reason)

def verify(doc):
    services = doc.get("services")
    require(isinstance(services, dict) and sorted(services)==["model-compass"], "unexpected services")
    s = services["model-compass"]
    require(s.get("read_only") is True, "writable rootfs")
    require(str(s.get("user")) == "65532:65532", "unexpected container identity")
    require("ALL" in s.get("cap_drop", []), "linux capabilities not fully dropped")
    require("no-new-privileges:true" in s.get("security_opt", []), "privilege escalation permitted")
    require(s.get("privileged") is not True, "privileged container")
    require(s.get("network_mode") != "host", "host network bypass")
    require(not s.get("devices"), "host devices assigned")
    require(int(s.get("pids_limit", 0)) > 0, "missing process budget")
    require(s.get("mem_limit"), "missing memory budget")
    require(not any("docker.sock" in str(m) for m in s.get("volumes", [])), "docker socket injected")
    mounts = {m["target"]:m for m in s.get("volumes", []) if isinstance(m,dict)}
    require(set(mounts)=={"/state","/run/secrets/compass_token"}, "unexpected persistent mounts")
    for dest, m in mounts.items():
        require(m.get("type")=="bind" and m.get("read_only") is True, "state/secret is not read-only bind: "+dest)
        require(str(m.get("source","")).startswith("/"), "relative/anonymous volume: "+dest)
    ports=s.get("ports",[])
    require(len(ports)==1, "unexpected published port count")
    p=ports[0]
    require(isinstance(p,dict), "unexpected normalized Compose port")
    require(str(p.get("host_ip"))=="127.0.0.1" and int(p.get("target"))==8088, "port not strict loopback-bound")
    require(s.get("restart")=="unless-stopped", "nonconvergent restart")
    environment=s.get("environment") or {}
    require(environment.get("COMPASS_TOKEN_FILE")=="/run/secrets/compass_token", "missing external token")
    require(environment.get("COMPASS_SNAPSHOT_FILE")=="/state/snapshot.json", "missing external state path")
    require("MODEL_COMPASS_IMAGE" not in str(s.get("image","")), "unresolved image")
    require("api_key" not in str(s).lower() and "password" not in str(s).lower(), "plaintext credentials exposed in IR")
    return True

if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("usage: verify_compose.py <normalized-compose.json>")
    path=pathlib.Path(sys.argv[1])
    require(path.is_file() and path.stat().st_size<262144, "invalid normalized source")
    verify(json.loads(path.read_text(encoding="utf-8")))
    print("PASS: source normalized Compose external-state/read-only isolation policy")
