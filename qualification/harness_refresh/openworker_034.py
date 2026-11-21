#!/usr/bin/env python3
"""Pinned OpenWorker 0.3.4 source candidate, local OCI only (NOT BUILD_ADMITTED).

Never publishes, touches a sovereign host, or injects model credentials.
Upstream pyproject dependency ranges are not frozen; hold release until a
dependency-locked, separately independent same-task qualification is accepted.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
from qualification.package_artifact_oci import package
from qualification.hydrate_oci_layout import hydrate

REPO="https://github.com/andrewyng/openworker.git"
SHA="d1b8cd69ceccb10e75bb58ea133a5cf7cb981b89"
VERSION="0.3.4"
RECIPE="openworker-034-public-unlocked-python311-candidate-v1"
def digest(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()
def run(argv:list[str],*,cwd:Path|None=None,env:dict|None=None)->str:
    p=subprocess.run(argv,cwd=cwd,env=env,text=True,capture_output=True,
                     check=False,timeout=1500)
    if p.returncode:
        raise RuntimeError("candidate stage failed: "+Path(argv[0]).name+" rc="+str(p.returncode))
    return p.stdout.strip()
def source_check(src:Path):
    source=tomllib.loads((src/"pyproject.toml").read_text())
    if source["project"]["name"]!="openworker" or source["project"]["version"]!=VERSION:
        raise ValueError("upstream name/version changed")
    if run(["git","-C",str(src),"rev-parse","HEAD"])!=SHA:
        raise ValueError("upstream HEAD not exact source candidate")
def manifest(root:Path)->list[dict]:
    rows=[]
    for p in sorted(root.rglob("*")):
        if p.is_symlink():raise ValueError("symlink payload")
        if not p.is_file():continue
        rows.append({"path":p.relative_to(root).as_posix(),
                     "sha256":digest(p),"bytes":p.stat().st_size})
        if len(rows)>2000:raise ValueError("unbounded wheelhouse")
    if not rows:raise ValueError("empty wheelhouse")
    return rows
def validate_local(out:Path)->dict:
    receipt=json.loads((out/"payload/build-receipt.json").read_text())
    if receipt.get("schema")!="agent-harness-refresh-candidate/v1" or receipt.get("source_commit")!=SHA:
        raise ValueError("wrong candidate source identity")
    if receipt["dependency_lock_digest"] is not None or receipt["admission_state"]!="CANDIDATE_UNLOCKED_DEPENDENCIES":
        raise ValueError("unearned source/release admission")
    if receipt["recipe"]!=RECIPE or receipt["version"]!=VERSION:
        raise ValueError("candidate recipe mismatch")
    files=manifest(out/"payload/wheelhouse")
    actual=[{"path":"wheelhouse/"+row["path"],"sha256":row["sha256"],"bytes":row["bytes"]} for row in files]
    if actual!=receipt["files"]:raise ValueError("artifact payload drift")
    with tempfile.TemporaryDirectory(prefix="openworker-candidate-verify-") as tmp:
        dest=Path(tmp)
        unpack=hydrate(out/"oci",dest,"artifact")
        expected=json.loads((out/"layout-receipt.json").read_text())
        if unpack["manifest_digest"]!=expected["manifest_digest"]:
            raise ValueError("OCI layout digest drift")
        if (dest/"artifact/build-receipt.json").read_bytes()!=(out/"payload/build-receipt.json").read_bytes():
            raise ValueError("hydrated receipt differs")
        for row in actual:
            p=dest/"artifact"/row["path"]
            if not p.is_file() or digest(p)!=row["sha256"] or p.stat().st_size!=row["bytes"]:
                raise ValueError("hydrated wheelhouse drift")
    return {"schema":"openworker-034-candidate-local-verify/v1",
            "state":"LOCAL_CANDIDATE_VERIFIED","source_commit":SHA,
            "version":VERSION,"payload_wheels":len(files),
            "manifest_digest":expected["manifest_digest"],
            "dependency_lock":"MISSING_HOLD",
            "registry_publication":"NOT_PERFORMED",
            "task_qualification":"NOT_PERFORMED",
            "production_admission":"NOT_GRANTED"}
def build(out:Path)->dict:
    if out.exists():return {**validate_local(out),"reused":True}
    if platform.system()!="Linux" or platform.machine() not in ("x86_64","AMD64"):
        raise ValueError("only public linux x64 candidate")
    if sys.version_info[:2]!=(3,11):
        raise ValueError("Python 3.11 realization required")
    if not out.parent.exists():raise ValueError("missing output parent")
    with tempfile.TemporaryDirectory(prefix=".openworker-034-build-",dir=out.parent) as tmp:
        t=Path(tmp)
        source=t/"src"
        run(["git","clone","--quiet","--filter=blob:none","--no-checkout",REPO,str(source)])
        run(["git","-C",str(source),"checkout","--quiet","--detach",SHA])
        source_check(source)
        venv=t/"build-venv"
        run([sys.executable,"-m","venv",str(venv)])
        py=str(venv/"bin/python")
        run([py,"-m","pip","install","--disable-pip-version-check","--no-input",
             "pip==25.2","wheel==0.45.1","build==1.3.0"])
        wh=t/"payload/wheelhouse"
        wh.mkdir(parents=True)
        run([py,"-m","pip","wheel","--disable-pip-version-check","--no-input",
             "--wheel-dir",str(wh),str(source)])
        wheels=sorted(wh.glob("*.whl"))
        if not wheels:raise ValueError("empty wheels")
        verify_env={**os.environ,"PIP_NO_INDEX":"1","PIP_DISABLE_PIP_VERSION_CHECK":"1"}
        smoke=t/"smoke"
        run([sys.executable,"-m","venv",str(smoke)])
        # No resolver/network: all exact built wheels only.
        run([str(smoke/"bin/python"),"-m","pip","install","--no-index","--no-deps",
             *map(str,wheels)],env=verify_env)
        run([str(smoke/"bin/python"),"-c",
            "import importlib.metadata as m; import coworker; import coworker.engine; "
            "assert m.version('openworker')=='0.3.4'"],env=verify_env)
        run([str(smoke/"bin/openworker"),"--help"],env=verify_env)
        rows=manifest(wh)
        receipt={"schema":"agent-harness-refresh-candidate/v1",
            "harness":"openworker","version":VERSION,"source_commit":SHA,
            "source_repo":REPO,"recipe":RECIPE,"python":platform.python_version(),
            "python_abi":sysconfig.get_config_var("SOABI"),
            "dependency_lock_digest":None,
            "admission_state":"CANDIDATE_UNLOCKED_DEPENDENCIES",
            "files":[{"path":"wheelhouse/"+a["path"],"sha256":a["sha256"],
                      "bytes":a["bytes"]} for a in rows],
            "independent_checks":["source-sha","pyproject-version",
                                  "offline-install","native-import","cli-help",
                                  "oci-rehydrate-and-sha"],
            "model_inference":"NOT_PERFORMED",
            "production_admission":"NOT_GRANTED"}
        (t/"payload/build-receipt.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
        layout=package(t/"payload",t/"oci","artifact","amd64","linux")
        (t/"layout-receipt.json").write_text(json.dumps(layout,sort_keys=True,indent=2)+"\n")
        result=validate_local(t)
        # Only a verified inert candidate/receipt is promoted; never ship src or venv.
        stage=t/"output"
        stage.mkdir()
        for name in ("payload","oci"):
            shutil.move(str(t/name),str(stage/name))
        shutil.copy2(t/"layout-receipt.json",stage/"layout-receipt.json")
        stage.rename(out)
        return {**result,"reused":False}
def selftest():
    assert re.fullmatch("[a-f0-9]{40}",SHA) and VERSION=="0.3.4"
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)/"wheels";root.mkdir()
        (root/"x.whl").write_bytes(b"abc")
        one=manifest(root)
        (root/"x.whl").write_bytes(b"abcd")
        assert manifest(root)!=one
        (root/"bad.whl").symlink_to(root/"x.whl")
        try:manifest(root)
        except ValueError:pass
        else:raise AssertionError("unsafe wheelhouse symlink accepted")
    print(json.dumps({"schema":"openworker-034-refresh-critic/v1",
      "verdict":"PASS","native_build":"NOT_PERFORMED","negative_cases":2,
      "admission":"NOT_GRANTED"},sort_keys=True))
def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("self-test","build","verify"))
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    if a.action=="self-test":selftest();return
    if a.output is None:p.error("--output required")
    print(json.dumps(build(a.output) if a.action=="build" else validate_local(a.output),sort_keys=True))
if __name__=="__main__":main()
