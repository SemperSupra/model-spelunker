#!/usr/bin/env python3
"""Pinned Goose 1.60.2 rustls-only local native + rootless OCI candidate.

No registry publication, credentials or model inference. Source and feature
closure must be independently reviewed for release admission.
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

SHA="fb55b5a6d7f5b5df96c8f817f1cde6a81880d9f1"
VERSION="1.60.2"
RUST="1.99.0"
RECIPE="goose-1602-source-rustls-disable-update-candidate-v1"
FEATURES=["rustls-tls","disable-update"]
def hash_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda:f.read(1024*1024),b""):h.update(c)
    return h.hexdigest()
def git_source(path:Path):
    p=subprocess.run(["git","-C",str(path),"rev-parse","HEAD"],capture_output=True,text=True,check=False)
    if p.returncode or p.stdout.strip()!=SHA:raise ValueError("source HEAD drift")
    c=tomllib.loads((path/"Cargo.toml").read_text())
    t=tomllib.loads((path/"rust-toolchain.toml").read_text())
    cli=tomllib.loads((path/"crates/goose-cli/Cargo.toml").read_text())
    if (c["workspace"]["package"]["version"]!=VERSION
        or t["toolchain"]["channel"]!=RUST
        or cli["package"]["name"]!="goose-cli"
        or any(x not in cli["features"] for x in FEATURES)):
        raise ValueError("Goose source/release/toolchain feature drift")
def check_local(out:Path)->dict:
    p=out/"payload"
    receipt=json.loads((p/"build-receipt.json").read_text())
    expected={"schema":"agent-harness-refresh-candidate/v1",
              "harness":"goose","version":VERSION,"source_commit":SHA,
              "source_toolchain":RUST,"recipe":RECIPE,
              "release_admission":"NOT_GRANTED",
              "model_task_qualification":"NOT_PERFORMED"}
    if any(receipt.get(k)!=v for k,v in expected.items()):
        raise ValueError("incorrect source/release claims")
    if receipt.get("features")!=FEATURES:raise ValueError("feature set drift")
    binary=p/"goose"
    if binary.is_symlink() or not binary.is_file():raise ValueError("missing native source binary")
    if binary.stat().st_size!=receipt["binary_bytes"] or hash_file(binary)!=receipt["binary_sha256"]:
        raise ValueError("native Goose hash drift")
    with tempfile.TemporaryDirectory(prefix="goose-candidate-hydrated-") as tmp:
        root=Path(tmp)
        result=hydrate(out/"oci",root,"artifact")
        if result["manifest_digest"]!=json.loads((out/"layout-receipt.json").read_text())["manifest_digest"]:
            raise ValueError("layout digest mismatch")
        for name in ("goose","build-receipt.json"):
            if hash_file(root/"artifact"/name)!=hash_file(p/name):
                raise ValueError("hydrated payload differs")
    return {"schema":"goose-1602-native-candidate-verify/v1",
            "state":"LOCAL_CANDIDATE_VERIFIED","version":VERSION,
            "source_commit":SHA,"binary_sha256":receipt["binary_sha256"],
            "oci_manifest_digest":result["manifest_digest"],
            "registry_publication":"NOT_PERFORMED",
            "model_inference":"NOT_PERFORMED",
            "production_admission":"NOT_GRANTED"}
def stage(src:Path,binary:Path,out:Path):
    if out.exists():return {**check_local(out),"reused":True}
    if not out.parent.is_dir():raise ValueError("output parent missing")
    git_source(src)
    if binary.is_symlink() or not binary.is_file():raise ValueError("missing native compiled binary")
    if platform.system()!="Linux" or platform.machine()!="x86_64":
        raise ValueError("Goose candidate target Linux x86_64 only")
    for command in ([str(binary),"--version"],[str(binary),"--help"]):
        p=subprocess.run(command,capture_output=True,text=True,check=False,timeout=35)
        if p.returncode:raise ValueError("native Goose CLI command failed")
        if command[-1]=="--version" and VERSION not in p.stdout+p.stderr:
            raise ValueError("native Goose version mismatch")
    with tempfile.TemporaryDirectory(prefix="goose-1602-oci-",dir=out.parent) as td:
        tmp=Path(td)
        payload=tmp/"payload";payload.mkdir()
        target=payload/"goose";shutil.copy2(binary,target);target.chmod(0o755)
        lock=src/"Cargo.lock"
        receipt={"schema":"agent-harness-refresh-candidate/v1","harness":"goose",
                 "version":VERSION,"source_commit":SHA,"source_toolchain":RUST,
                 "recipe":RECIPE,"features":FEATURES,
                 "cargo_lock_sha256":hash_file(lock),
                 "binary_sha256":hash_file(target),"binary_bytes":target.stat().st_size,
                 "release_admission":"NOT_GRANTED",
                 "model_task_qualification":"NOT_PERFORMED",
                 "production_admission":"NOT_GRANTED"}
        (payload/"build-receipt.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
        meta=package(payload,tmp/"oci","artifact","amd64","linux")
        (tmp/"layout-receipt.json").write_text(json.dumps(meta,sort_keys=True,indent=2)+"\n")
        result=check_local(tmp)
        tmp_out=tmp/"result";tmp_out.mkdir()
        for name in ("payload","oci","layout-receipt.json"):
            shutil.move(str(tmp/name),str(tmp_out/name))
        tmp_out.rename(out)
    return {**result,"reused":False}
def selftest():
    assert len(SHA)==40 and re.fullmatch("[a-f0-9]{40}",SHA)
    assert RUST=="1.99.0" and FEATURES==["rustls-tls","disable-update"]
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"binary";p.write_bytes(b"good")
        h=hash_file(p);p.write_bytes(b"tamper")
        assert hash_file(p)!=h
    print(json.dumps({"schema":"goose-1602-candidate-critic/v1",
       "state":"PASS","source_rev":SHA,"version":VERSION,
       "source_compilation":"NOT_PERFORMED","release_admission":"NOT_GRANTED"}))
def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("self-test","stage","verify"))
    p.add_argument("--source",type=Path)
    p.add_argument("--binary",type=Path)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    if a.action=="self-test":selftest();return
    if a.output is None:p.error("--output required")
    if a.action=="stage":
        if not a.source or not a.binary:p.error("stage requires --source and --binary")
        result=stage(a.source,a.binary,a.output)
    else:result=check_local(a.output)
    print(json.dumps(result,sort_keys=True))
if __name__=="__main__":main()
