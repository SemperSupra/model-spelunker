#!/usr/bin/env python3
"""Exact-source Codex exec v0.171.0 native candidate, NOT authorized release.

The historical compile-only recursion limit 256 patch is now in upstream.
Never insert a second patch, grant sandbox/agent authority, or write GHCR.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import tomllib
from qualification.package_artifact_oci import package
from qualification.hydrate_oci_layout import hydrate

SOURCE="ccf9be8cc458bd6b8336fe84d68d8893f2691a5e"
VERSION="0.171.0"
RUST="1.99.1"
RECIPE="codex-exec-0171-upstream-recursion256-no-patch-v1"
NAME="codex-exec"
def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda:f.read(1024*1024),b""):h.update(part)
    return h.hexdigest()
def inspect_source(path:Path)->dict:
    run=subprocess.run(["git","-C",str(path),"rev-parse","HEAD"],capture_output=True,text=True,check=False)
    if run.returncode or run.stdout.strip()!=SOURCE:
        raise ValueError("wrong frozen Codex source")
    src=path/"codex-rs"
    workspace=tomllib.loads((src/"Cargo.toml").read_text())
    toolchain=tomllib.loads((src/"rust-toolchain.toml").read_text())
    execpkg=tomllib.loads((src/"exec/Cargo.toml").read_text())
    main=(src/"exec/src/main.rs").read_text()
    if (workspace["workspace"]["package"]["version"]!=VERSION
      or toolchain["toolchain"]["channel"]!=RUST
      or execpkg["package"]["name"]!=NAME
      or main.count('#![recursion_limit = "256"]')!=1):
        raise ValueError("upstream Codex compile or release contract drift")
    return {"source":SOURCE,"version":VERSION,"toolchain":RUST,
            "recursion_patch":"UPSTREAM_ALREADY_PRESENT_DO_NOT_REAPPLY"}
def verify(out:Path)->dict:
    p=out/"payload"; receipt=json.loads((p/"build-receipt.json").read_text())
    expected={"schema":"agent-harness-refresh-candidate/v1","harness":NAME,
              "version":VERSION,"source_commit":SOURCE,"toolchain":RUST,
              "recipe":RECIPE,
              "patch":"NONE_UPSTREAM_RECURSION256_PRESENT",
              "production_admission":"NOT_GRANTED",
              "actor_task_qualification":"NOT_PERFORMED"}
    if any(receipt.get(k)!=v for k,v in expected.items()):
        raise ValueError("Codex candidate has unsupported claims")
    binary=p/NAME
    if binary.is_symlink() or not binary.is_file():
        raise ValueError("native codex-exec missing")
    if binary.stat().st_size!=receipt["binary_bytes"] or sha(binary)!=receipt["binary_sha256"]:
        raise ValueError("codex native bytes drift")
    with tempfile.TemporaryDirectory(prefix="codex-0171-oci-read-") as td:
        root=Path(td)
        meta=hydrate(out/"oci",root,"artifact")
        if meta["manifest_digest"]!=json.loads((out/"layout-receipt.json").read_text())["manifest_digest"]:
            raise ValueError("OCI manifest digest drift")
        for name in (NAME,"build-receipt.json"):
            if sha(root/"artifact"/name)!=sha(p/name):raise ValueError("OCI payload drift")
    return {"schema":"codex-exec-0171-candidate-verify/v1",
            "state":"LOCAL_CANDIDATE_VERIFIED","source_sha":SOURCE,
            "version":VERSION,"manifest_digest":meta["manifest_digest"],
            "native_sha256":receipt["binary_sha256"],
            "upstream_recursion_patch":"PRESENT",
            "registry_publication":"NOT_PERFORMED",
            "model_inference":"NOT_PERFORMED",
            "production_admission":"NOT_GRANTED"}
def stage(source:Path,binary:Path,out:Path)->dict:
    if out.exists():return {**verify(out),"reused":True}
    if not out.parent.is_dir():raise ValueError("missing out parent")
    if platform.system()!="Linux" or platform.machine()!="x86_64":
        raise ValueError("candidate only Linux amd64")
    inspect_source(source)
    if binary.is_symlink() or not binary.is_file():raise ValueError("native binary not present")
    for suffix in (["--version"],["--help"]):
        p=subprocess.run([str(binary),*suffix],capture_output=True,text=True,check=False,timeout=45)
        if p.returncode:raise ValueError("codex-exec native smoke failed")
        if suffix==["--version"] and VERSION not in p.stdout+p.stderr:
            raise ValueError("codex-exec CLI version mismatched")
    with tempfile.TemporaryDirectory(prefix="codex-0171-candidate-",dir=out.parent) as td:
        t=Path(td);payload=t/"payload";payload.mkdir()
        target=payload/NAME
        shutil.copy2(binary,target);target.chmod(0o755)
        lock=source/"codex-rs/Cargo.lock"
        receipt={"schema":"agent-harness-refresh-candidate/v1",
            "harness":NAME,"version":VERSION,"source_commit":SOURCE,
            "toolchain":RUST,"recipe":RECIPE,
            "patch":"NONE_UPSTREAM_RECURSION256_PRESENT",
            "binary_sha256":sha(target),"binary_bytes":target.stat().st_size,
            "cargo_lock_sha256":sha(lock),
            "production_admission":"NOT_GRANTED",
            "actor_task_qualification":"NOT_PERFORMED"}
        (payload/"build-receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
        meta=package(payload,t/"oci","artifact","amd64","linux")
        (t/"layout-receipt.json").write_text(json.dumps(meta,indent=2,sort_keys=True)+"\n")
        result=verify(t)
        candidate=t/"result";candidate.mkdir()
        for file in ("payload","oci","layout-receipt.json"):
            shutil.move(str(t/file),str(candidate/file))
        candidate.rename(out)
    return {**result,"reused":False}
def selftest():
    assert re.fullmatch(r"[a-f0-9]{40}",SOURCE)
    assert RECIPE.endswith("no-patch-v1")
    assert RUST=="1.99.1" and VERSION=="0.171.0"
    print(json.dumps({"schema":"codex-exec-0171-refresh-critic/v1",
          "state":"PASS","new_patch":"FORBIDDEN",
          "source_build":"NOT_PERFORMED","production_admission":"NOT_GRANTED"},sort_keys=True))
def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("self-test","stage","verify"))
    p.add_argument("--source",type=Path)
    p.add_argument("--binary",type=Path)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    if a.action=="self-test":selftest();return
    if a.output is None:p.error("--output required")
    if a.action=="verify":result=verify(a.output)
    else:
        if a.source is None or a.binary is None:p.error("stage requires --source and --binary")
        result=stage(a.source,a.binary,a.output)
    print(json.dumps(result,sort_keys=True))
if __name__=="__main__":main()
