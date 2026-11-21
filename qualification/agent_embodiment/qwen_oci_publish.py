#!/usr/bin/env python3
"""Protected-main rootless GHCR publisher for the verified Qwen OCI distribution.

Reuses the existing OpenWorker producer's pinned regctl transport, image digest
and copy routines. Publication is distinct from local verification and never
qualifies model tasks or grants workcell authority. PR CI runs only self-test.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from qualification.agent_embodiment.qwen_oci import verify as verify_local, sha, RELEASE_PATH
from qualification.hydrate_oci_layout import hydrate
from qualification.qwencode_public import kit
from qualification.sovereign_foundry_openworker import regctl_path, registry_copy, image_digest

IMAGE="ghcr.io/sempersupra/model-spelunker-harness-qwencode"

def admission_context(env: dict) -> str:
    """Environmental admission guardrail, not proof of runner identity.

    The *real* access boundary is the GitHub Actions main-only publish job with
    scoped packages:write token, never a user-editable JSON field or shell var.
    """
    expected={
        "GITHUB_ACTIONS":"true",
        "GITHUB_REPOSITORY":"SemperSupra/model-spelunker",
        "GITHUB_EVENT_NAME":"push",
        "GITHUB_REF":"refs/heads/main",
    }
    if any(env.get(k)!=v for k,v in expected.items()):
        raise ValueError("not a trusted-main publication workflow context")
    revision=env.get("GITHUB_SHA","")
    if not re.fullmatch(r"[a-f0-9]{40}",revision):
        raise ValueError("missing exact head source SHA")
    return revision

def tag_for(digest: str, source_sha: str) -> str:
    if not re.fullmatch(r"sha256:[a-f0-9]{64}",digest):
        raise ValueError("invalid immutable manifest digest")
    if not re.fullmatch(r"[a-f0-9]{40}",source_sha):
        raise ValueError("invalid source sha")
    return "src-"+source_sha[:12]+"-oci-"+digest.split(":")[1][:16]

def valid_actor(actor: str) -> bool:
    return isinstance(actor,str) and bool(re.fullmatch(r"[A-Za-z0-9-]{1,39}(?:\[bot\])?",actor))

def login(regctl: Path, config: Path, token: str, actor: str):
    if not token or not valid_actor(actor):
        raise ValueError("scoped registry token/actor absent")
    env={**os.environ,"REGCTL_CONFIG":str(config)}
    result=subprocess.run([str(regctl),"registry","login","ghcr.io",
                "-u",actor,"--pass-stdin"],input=token+"\n",text=True,
                env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                check=False)
    if result.returncode:
        raise RuntimeError("GHCR login rejected by scoped token")

def independently_admit(regctl: Path, config: Path, immutable_ref: str,
                        expected_digest: str, local_build: Path,
                        work: Path) -> dict:
    remote=work/"fetched-oci"
    registry_copy(regctl,config,immutable_ref,"ocidir://"+str(remote)+":artifact")
    extracted=work/"hydrated"
    summary=hydrate(remote,extracted,"artifact")
    if summary["manifest_digest"]!=expected_digest:
        raise ValueError("remote OCI manifest mismatch")
    received=extracted/"artifact"
    source_receipt=(local_build/"payload/build-receipt.json").read_bytes()
    if (received/"build-receipt.json").read_bytes()!=source_receipt:
        raise ValueError("remote build-receipt bytes differ")
    receipt=json.loads(source_receipt)
    for entry in receipt["files"]:
        f=received/entry["path"]
        if f.is_symlink() or not f.is_file() or f.stat().st_size!=entry["bytes"]:
            raise ValueError("remote payload file type/length mismatch")
        if sha(f)!=entry["sha256"]:
            raise ValueError("remote payload hash mismatch")
    if len(receipt["files"])!=5:
        raise ValueError("unrecognized published payload shape")
    archive=received/RELEASE_PATH
    manifest=kit.load_manifest()
    kit.verify(archive,manifest["platforms"]["linux-x64"])
    native=kit.smoke(manifest,"linux-x64",archive,work/"native-smoke")
    if native["native_cli"]!="PASS":
        raise ValueError("remote pinned Qwen CLI not runnable")
    return {
        "state":"BUILD_ADMITTED","framework":"qwen-code",
        "source_commit":receipt["source_commit"],
        "manifest_digest":expected_digest,
        "immutable_ref":immutable_ref,
        "payload_files":len(receipt["files"]),
        "independent_checks":[
            "remote-manifest-digest","remote-build-receipt-exact-bytes",
            "remote-payload-file-hashes","official-release-digest",
            "native-cli-version"
        ],
        "actor_task_qualification":"NOT_PERFORMED",
        "workcell_admission":"NOT_GRANTED",
        "model_inference":"NOT_PERFORMED"
    }

def publish(out: Path,env: dict) -> dict:
    sha_head=admission_context(env)
    local=verify_local(out)
    record=json.loads((out/"payload/build-receipt.json").read_text())
    if record["source_commit"]!=sha_head:
        raise ValueError("output was not built from exact trusted main revision")
    expected=local["artifact_manifest_digest"]
    image=IMAGE
    destination=image+":"+tag_for(expected,sha_head)
    token=env.get("GHCR_TOKEN","")
    actor=env.get("GITHUB_ACTOR","")
    if not token:
        raise ValueError("publisher is missing its scoped GHCR token")
    # Executable staging stays on user-owned executable RUNNER_TEMP. The
    # credential config is ephemeral, 0700, never an uploaded output.
    with tempfile.TemporaryDirectory(prefix=".qwen-ghcr-exec-",dir=str(out.parent)) as exec_td, \
         tempfile.TemporaryDirectory(prefix=".qwen-ghcr-auth-",dir=str(out.parent)) as auth_td:
        exec_dir=Path(exec_td)
        auth_dir=Path(auth_td)
        exec_dir.chmod(0o700)
        auth_dir.chmod(0o700)
        client=regctl_path(exec_dir)
        cfg=auth_dir/"regctl.json"
        login(client,cfg,token,actor)
        prior=image_digest(client,cfg,destination)
        if prior is not None and prior!=expected:
            raise ValueError("immutable tag would be reassigned")
        if prior is None:
            registry_copy(client,cfg,"ocidir://"+str(out/"oci")+":artifact",destination)
        actual=image_digest(client,cfg,destination)
        if actual!=expected:
            raise ValueError("registry manifest differs after publish")
        immutable=image+"@"+expected
        result=independently_admit(client,cfg,immutable,expected,out,exec_dir)
    return {
        "schema":"qwen-ghcr-publish-admission/v1",**result,
        "publication":"GHCR_DIGEST_CONFIRMED",
        "source_classification":"PUBLIC_SYNTHETIC",
        "registry_image":image
    }

def selftest():
    s="a"*40
    digest="sha256:"+"f"*64
    assert tag_for(digest,s)=="src-"+"a"*12+"-oci-"+"f"*16
    good={
        "GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":"SemperSupra/model-spelunker",
        "GITHUB_EVENT_NAME":"push","GITHUB_REF":"refs/heads/main","GITHUB_SHA":s
    }
    assert admission_context(good)==s
    assert valid_actor("github-actions[bot]") and valid_actor("mark-e-deyoung")
    for actor in ("","../bad","a b","[bot]","evil;command"):
        assert not valid_actor(actor), "unsafe registry actor admitted"
    for key,bad in (
        ("GITHUB_REPOSITORY","SemperSupra/another"),
        ("GITHUB_REF","refs/heads/feature"),
        ("GITHUB_EVENT_NAME","pull_request"),
        ("GITHUB_ACTIONS","false"),
        ("GITHUB_SHA","bad")):
        changed=dict(good);changed[key]=bad
        try:admission_context(changed)
        except ValueError:pass
        else:raise AssertionError("invalid publisher context admitted: "+key)
    for bad in ("sha256:"+"F"*64,"sha256:"+"a"*63,"sha512:"+"a"*64):
        try:tag_for(bad,s)
        except ValueError:pass
        else:raise AssertionError("invalid registry digest admitted")
    print(json.dumps({"schema":"qwen-ghcr-publication-offline-critic/v1",
      "state":"PASS","negative_contexts":5,"negative_digests":3,"negative_registry_actors":5,
      "publication":"NOT_PERFORMED","real_registry":"NOT_CONTACTED"},sort_keys=True))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("self-test","publish"))
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    if args.action=="self-test":
        selftest();return
    if not args.output:p.error("--output required for publish")
    out=args.output.resolve()
    # Do not write stdout containing raw registry credentials or errors.
    print(json.dumps(publish(out,dict(os.environ)),sort_keys=True))

if __name__=="__main__":main()
