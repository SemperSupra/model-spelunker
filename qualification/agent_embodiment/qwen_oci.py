#!/usr/bin/env python3
"""Qwen Code release OCI carrier, *not* a runnable container or a model admission.

Reuses existing Model Spelunker deterministic FROM-scratch OCI pack/hydrate.
Never publishes to GHCR. Requires exact upstream archive already verified,
and generates independently rehydratable distribution and data-only receipts.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

from qualification.package_artifact_oci import package
from qualification.hydrate_oci_layout import hydrate
from qualification.agent_embodiment.qwen_embody import PROFILE, load_profile, canonical
from qualification.qwencode_public import kit

FILES={
    "qualification/agent_embodiment/qwen-public-linux.json":PROFILE,
    "qualification/agent_embodiment/qwen_embody.py":Path(__file__).with_name("qwen_embody.py"),
    "qualification/qwencode_public/kit.py":kit.HERE/"kit.py",
    "qualification/qwencode_public/release-manifest.json":kit.MANIFEST,
}
RECIPE="qwencode-0.28.3-linux-x64-release-carrier-v1"
RELEASE_PATH="upstream/qwen-code-linux-x64.tar.gz"

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def inventory(payload: Path, *, include_receipt: bool=False) -> list[dict]:
    result=[]
    for file in sorted(payload.rglob("*")):
        if file.is_symlink():raise ValueError("payload symlinks forbidden")
        if not file.is_file():continue
        relative=file.relative_to(payload).as_posix()
        if relative=="build-receipt.json" and not include_receipt:continue
        result.append({"path":relative,"sha256":sha(file),"bytes":file.stat().st_size})
    return result

def source_identity(source_commit: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{40}",source_commit):
        raise ValueError("source commit must be exact 40-digit SHA1")
    return source_commit

def verify(out: Path) -> dict:
    receipt=json.loads((out/"payload/build-receipt.json").read_text())
    if receipt.get("schema")!="agent-harness-oci-build/v1" or receipt.get("recipe")!=RECIPE:
        raise ValueError("incorrect Qwen build receipt")
    if receipt.get("production_admission")!="NOT_GRANTED":raise ValueError("false production claim")
    files=inventory(out/"payload")
    if files!=receipt["files"] or len(files)!=5:
        raise ValueError("payload inventory mismatch")
    profile=load_profile()
    if receipt["profile_sha256"]!=hashlib.sha256(canonical(profile)).hexdigest():
        raise ValueError("profile drift")
    manifest=kit.load_manifest()
    archive=out/"payload"/RELEASE_PATH
    kit.verify(archive,manifest["platforms"]["linux-x64"])
    stored=json.loads((out/"layout-receipt.json").read_text())
    with tempfile.TemporaryDirectory(prefix="qwen-oci-verify-") as tmp:
        hydrated=Path(tmp)
        summary=hydrate(out/"oci",hydrated,"artifact")
        if summary["manifest_digest"]!=stored["manifest_digest"]:
            raise ValueError("OCI manifest digest drift")
        installed=hydrated/"artifact"
        for row in receipt["files"]:
            f=installed/row["path"]
            if not f.is_file() or f.stat().st_size!=row["bytes"] or sha(f)!=row["sha256"]:
                raise ValueError("rehydrated file digest mismatch")
        if (installed/"build-receipt.json").read_bytes()!=(out/"payload/build-receipt.json").read_bytes():
            raise ValueError("rehydrated receipt drift")
    return {"schema":"agent-harness-oci-local-admission/v1",
            "state":"LOCAL_VERIFIED","artifact_manifest_digest":stored["manifest_digest"],
            "payload_file_count":len(files),"source_commit":receipt["source_commit"],
            "publish":"NOT_PERFORMED","production_admission":"NOT_GRANTED",
            "actor_task_qualification":"NOT_PERFORMED"}

def build(archive: Path,out: Path,source_commit: str) -> dict:
    source_identity(source_commit)
    manifest=kit.load_manifest()
    kit.verify(archive,manifest["platforms"]["linux-x64"])
    if out.exists():
        res=verify(out)
        old=json.loads((out/"payload/build-receipt.json").read_text())
        if old["source_commit"]!=source_commit:
            raise ValueError("existing output belongs to another source commit")
        return {**res,"state":"ALREADY_BUILT"}
    if not out.parent.is_dir():raise ValueError("output parent must already exist")
    with tempfile.TemporaryDirectory(prefix=".qwen-oci-stage-",dir=out.parent) as tmp:
        stage=Path(tmp)
        payload=stage/"payload"
        for name,path in FILES.items():
            target=payload/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
        target=payload/RELEASE_PATH
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(archive,target)
        files=inventory(payload)
        if len(files)!=5:raise ValueError("wrong payload count")
        receipt={
            "schema":"agent-harness-oci-build/v1","recipe":RECIPE,
            "framework":"qwen-code","version":manifest["version"],
            "source_commit":source_commit,
            "profile_sha256":hashlib.sha256(canonical(load_profile())).hexdigest(),
            "release_sha256":manifest["platforms"]["linux-x64"]["sha256"],
            "platform":{"os":"linux","architecture":"amd64"},
            "files":files,"publication":"NOT_PERFORMED",
            "production_admission":"NOT_GRANTED",
            "actor_task_qualification":"NOT_PERFORMED"
        }
        (payload/"build-receipt.json").write_bytes(canonical(receipt))
        lay=package(payload,stage/"oci","artifact","amd64","linux")
        (stage/"layout-receipt.json").write_bytes(canonical(lay))
        verify(stage)
        # Atomic output promotion into a new unique name, never overwrite.
        stage.rename(out)
        return {**verify(out),"state":"LOCAL_VERIFIED"}

def selftest():
    import copy
    assert source_identity("a"*40)=="a"*40
    for bad in ("a"*39,"a"*41,"not-a-sha","A"*40):
        try:source_identity(bad)
        except ValueError:pass
        else:raise AssertionError("invalid source admitted")
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)/"data"
        p.mkdir()
        (p/"a").write_text("foo")
        one=inventory(p)
        assert len(one)==1 and one[0]["sha256"]==hashlib.sha256(b"foo").hexdigest()
        (p/"a").write_text("bar")
        assert inventory(p)!=one
        (p/"evil").symlink_to(p/"a")
        try:inventory(p)
        except ValueError:pass
        else:raise AssertionError("symlink admitted")
    print(json.dumps({"schema":"qwen-oci-source-critic/v1","status":"PASS",
                      "negative_source_ids":4,"negative_payload_mutants":2,
                      "registry_publish":"NOT_PERFORMED"}))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("self-test","build","verify"))
    p.add_argument("--archive",type=Path)
    p.add_argument("--output",type=Path)
    p.add_argument("--source-commit")
    a=p.parse_args()
    if a.action=="self-test":
        selftest();return
    if not a.output:p.error("--output is required")
    if a.action=="verify":row=verify(a.output)
    else:
        if not a.archive or not a.source_commit:
            p.error("build requires --archive and --source-commit")
        row=build(a.archive,a.output,a.source_commit)
    print(json.dumps(row,sort_keys=True))
if __name__=="__main__":main()
