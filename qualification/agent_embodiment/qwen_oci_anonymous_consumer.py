#!/usr/bin/env python3
"""Fresh public-runner unauthenticated GHCR Qwen carrier consumer.

Explicitly distinguish registry-public availability from existing authenticated
BUILD_ADMITTED evidence. No registry token, Docker, sudo or model inference.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from qualification.hydrate_oci_layout import hydrate
from qualification.qwencode_public import kit
from qualification.agent_embodiment.qwen_oci import sha, RELEASE_PATH

EXPECTED_IMAGE="ghcr.io/sempersupra/model-spelunker-harness-qwencode"
EXPECTED_DIGEST="sha256:506ef11f6cde829e8f31e3c9b9ca83903278b5a604038aaeda49271e538d3954"
EXPECTED_SOURCE="b92e9b8dc2bec74813584ad2e1177519b032dad3"
EXPECTED_REF=EXPECTED_IMAGE+"@"+EXPECTED_DIGEST

def check_ref(ref: str):
    if ref!=EXPECTED_REF or not re.fullmatch(
      r"ghcr\.io/[a-z0-9-]+/[a-z0-9._-]+@sha256:[a-f0-9]{64}",ref):
        raise ValueError("unadmitted GHCR artifact identity")

def inspect_hydrated(root: Path, manifest_digest: str) -> dict:
    if manifest_digest!=EXPECTED_DIGEST:
        raise ValueError("OCI digest does not equal source admitted digest")
    payload=root/"artifact"
    receipt_path=payload/"build-receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError("missing build receipt")
    receipt=json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("schema")!="agent-harness-oci-build/v1"
        or receipt.get("framework")!="qwen-code"
        or receipt.get("version")!="0.28.3"
        or receipt.get("source_commit")!=EXPECTED_SOURCE):
        raise ValueError("wrong harness/source from public OCI")
    rows=receipt.get("files")
    if not isinstance(rows,list) or len(rows)!=5:
        raise ValueError("unexpected public OCI payload inventory")
    for row in rows:
        name=row.get("path")
        if not isinstance(name,str):
            raise ValueError("invalid OCI path")
        p=(payload/name).resolve()
        if not p.is_relative_to(payload.resolve()) or p.is_symlink() or not p.is_file():
            raise ValueError("OCI payload missing or escaped")
        if p.stat().st_size!=row.get("bytes") or sha(p)!=row.get("sha256"):
            raise ValueError("OCI payload digest mismatch")
    manifest=kit.load_manifest()
    kit.verify(payload/RELEASE_PATH,manifest["platforms"]["linux-x64"])
    return {"schema":"qwen-ghcr-anonymous-consumer/v1",
        "artifact_ref":EXPECTED_REF,"manifest_digest":EXPECTED_DIGEST,
        "source_commit":EXPECTED_SOURCE,"payload_files_verified":len(rows),
        "upstream_release_verified":True}

def run(regctl: Path) -> dict:
    check_ref(EXPECTED_REF)
    if not regctl.is_file():raise ValueError("pinned rootless OCI reader missing")
    with tempfile.TemporaryDirectory(prefix="qwen-ghcr-anon-") as tmp:
        root=Path(tmp)
        layout=root/"oci"
        # Do not pass REGCTL_CONFIG or credentials; this tests anonymous use.
        env={"PATH":"/usr/bin:/bin","HOME":str(root)}
        fetch=subprocess.run([str(regctl),"image","copy",EXPECTED_REF,
                     "ocidir://"+str(layout)+":artifact"],
                     env=env,capture_output=True,text=True,check=False,timeout=140)
        if fetch.returncode:
            # Distinguish fact of rejection/unreachability without guessing
            # whether it is package visibility, network, registry or rate policy.
            return {"schema":"qwen-ghcr-anonymous-consumer/v1",
                "verdict":"ANONYMOUS_PULL_NOT_CONFIRMED",
                "transport":"FAILED_OR_DENIED",
                "actual_external_registry_contact":True,
                "model_inference":"NOT_PERFORMED","public_visibility":"UNVERIFIED"}
        hydrated=root/"unpacked"
        info=hydrate(layout,hydrated,"artifact")
        row=inspect_hydrated(hydrated,info["manifest_digest"])
        native=kit.smoke(kit.load_manifest(),"linux-x64",
                hydrated/"artifact"/RELEASE_PATH,root/"native")
        if native["native_cli"]!="PASS":raise ValueError("native Qwen smoke failed")
        return {**row,"verdict":"ANONYMOUS_FETCH_AND_NATIVE_SMOKE_PASS",
                "transport":"ANONYMOUS","actual_external_registry_contact":True,
                "public_visibility":"ANONYMOUS_READ_VERIFIED",
                "model_inference":"NOT_PERFORMED",
                "workcell_admission":"NOT_GRANTED"}

def selftest():
    check_ref(EXPECTED_REF)
    for bad in (
        EXPECTED_IMAGE+":latest",EXPECTED_IMAGE+"@sha256:"+"0"*64,
        EXPECTED_REF.upper(),"ghcr.io/other/other@"+EXPECTED_DIGEST,""):
        try:check_ref(bad)
        except ValueError:pass
        else:raise AssertionError("invalid GHCR ref accepted")
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/"artifact").mkdir()
        (root/"artifact/build-receipt.json").write_text(json.dumps({
          "schema":"agent-harness-oci-build/v1","framework":"qwen-code",
          "version":"0.28.3","source_commit":"bad","files":[]}))
        try:inspect_hydrated(root,EXPECTED_DIGEST)
        except ValueError:pass
        else:raise AssertionError("wrong source admitted")
        try:inspect_hydrated(root,"sha256:"+"0"*64)
        except ValueError:pass
        else:raise AssertionError("wrong OCI manifest admitted")
    print(json.dumps({"schema":"qwen-ghcr-anonymous-consumer-critic/v1",
        "state":"PASS","negative_refs":5,"negative_artifact_cases":2,
        "registry_not_contacted":True},sort_keys=True))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("self-test","probe"))
    p.add_argument("--regctl",type=Path)
    args=p.parse_args()
    if args.action=="self-test":
        selftest();return
    if not args.regctl:p.error("probe requires --regctl")
    result=run(args.regctl)
    print(json.dumps(result,sort_keys=True))
    if result.get("verdict")!="ANONYMOUS_FETCH_AND_NATIVE_SMOKE_PASS":
        raise SystemExit(1)
if __name__=="__main__":main()
