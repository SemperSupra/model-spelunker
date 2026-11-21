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

DLE_ISSUE=147
DLE_REPO="SemperSupra/model-spelunker"
DLE_MARKER="qwen-ghcr-foundry-admission:v1:"
REQUIRED_REMOTE_CHECKS=frozenset((
    "remote-manifest-digest","remote-build-receipt-exact-bytes",
    "remote-payload-file-hashes","official-release-digest",
    "native-cli-version"
))

def dle_record(receipt: dict,env: dict) -> dict:
    head=admission_context(env)
    digest=receipt.get("manifest_digest","")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}",digest):
        raise ValueError("no trustworthy remote digest")
    required={
        "schema":"qwen-ghcr-publish-admission/v1","state":"BUILD_ADMITTED",
        "publication":"GHCR_DIGEST_CONFIRMED",
        "source_commit":head,
        "immutable_ref":IMAGE+"@"+digest,
        "registry_image":IMAGE,
        "source_classification":"PUBLIC_SYNTHETIC",
        "actor_task_qualification":"NOT_PERFORMED",
        "workcell_admission":"NOT_GRANTED",
        "model_inference":"NOT_PERFORMED"
    }
    if any(receipt.get(k)!=v for k,v in required.items()):
        raise ValueError("non-admitted receipt state or source identity")
    if (not isinstance(receipt.get("independent_checks"),list)
        or frozenset(receipt["independent_checks"])!=REQUIRED_REMOTE_CHECKS
        or len(receipt["independent_checks"])!=len(REQUIRED_REMOTE_CHECKS)):
        raise ValueError("missing or unexpected independent remote checks")
    if receipt.get("payload_files")!=5:
        raise ValueError("unknown Qwen carrier file count")
    return {
        "schema":"model-spelunker-ghcr-dle/v1",
        "governing_issue":DLE_REPO+"#"+str(DLE_ISSUE),
        "source_commit":head,
        "harness":"qwen-code","platform":"linux-amd64",
        "registry_image":IMAGE,"immutable_ref":IMAGE+"@"+digest,
        "manifest_digest":digest,
        "build_state":"BUILD_ADMITTED",
        "independent_checks":sorted(REQUIRED_REMOTE_CHECKS),
        "payload_files":5,
        "model_inference":"NOT_PERFORMED",
        "actor_task_qualification":"NOT_PERFORMED",
        "production_admission":"NOT_GRANTED",
        "evidence_source":"GHCR_MAIN_ONLY_DIGEST_REFETCH"
    }

def dle_body(record: dict) -> str:
    marker="<!-- "+DLE_MARKER+record["manifest_digest"].split(":")[1]+" -->"
    return (marker+"\n### Qwen Code GHCR realization: BUILD_ADMITTED\n\n"
        "Main-only rootless publisher independently re-fetched the immutable digest, "
        "checked OCI manifest and original payload hashes, then smoked pinned native Qwen CLI. "
        "This is artifact acceptance, NOT model-task or production workcell admission.\n\n"
        +json.dumps(record,sort_keys=True,indent=2)+"\n")

def gh_api_json(args: list[str]):
    result=subprocess.run(["gh","api",*args],capture_output=True,text=True,check=False)
    if result.returncode:
        raise RuntimeError("GitHub DLE receipt transport unavailable")
    try:
        return json.loads(result.stdout)
    except ValueError as err:
        raise ValueError("malformed DLE API response") from err

def sync_dle(receipt: dict,env: dict) -> dict:
    record=dle_record(receipt,env)
    body=dle_body(record)
    resource="repos/"+DLE_REPO+"/issues/"+str(DLE_ISSUE)+"/comments"
    pages=gh_api_json(["--paginate","--slurp",resource+"?per_page=100"])
    if not isinstance(pages,list):
        raise ValueError("unexpected GitHub issue comment pagination")
    rows=[row for page in pages
          for row in (page if isinstance(page,list) else [page])]
    marker=body.splitlines()[0]
    previous=[row for row in rows
              if isinstance(row,dict) and marker in str(row.get("body",""))]
    if previous:
        if any(row.get("body")!=body for row in previous):
            raise ValueError("DLE immutable digest key has conflicting receipt")
        return {"state":"ALREADY_RECORDED",
                "comment_url":previous[0].get("html_url"),
                "manifest_digest":record["manifest_digest"]}
    posted=gh_api_json(["--method","POST",resource,"-f","body="+body])
    if not isinstance(posted,dict) or posted.get("body")!=body or not posted.get("html_url"):
        raise ValueError("DLE write acknowledgement is invalid")
    return {"state":"RECORDED","comment_url":posted["html_url"],
            "manifest_digest":record["manifest_digest"]}

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
    # Mock the registry transport to execute real publish() branching and
    # independently reject tag reassignment and invalid remote admission.
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(prefix="qwen-ghcr-test-") as temp:
        out=Path(temp)/"oci";(out/"payload").mkdir(parents=True)
        (out/"payload/build-receipt.json").write_text(json.dumps({"source_commit":s}))
        accepted={**good,"GHCR_TOKEN":"synthetic-local-only",
                  "GITHUB_ACTOR":"github-actions[bot]"}
        def run_case(prior,after,remote_ok=True):
            calls=[]
            digests=iter([prior,after])
            def copy(*args):
                calls.append((args[2],args[3]))
            def image_lookup(*args):
                return next(digests)
            def admission(*args):
                if not remote_ok:raise RuntimeError("synthetic remote evidence denied")
                return {"state":"BUILD_ADMITTED","immutable_ref":IMAGE+"@"+digest,
                        "actor_task_qualification":"NOT_PERFORMED"}
            with patch.dict(globals(),{
                  "verify_local":lambda *_:{"artifact_manifest_digest":digest},
                  "regctl_path":lambda *_:Path(temp)/"synthetic-regctl",
                  "login":lambda *args:None,
                  "image_digest":image_lookup,
                  "registry_copy":copy,
                  "independently_admit":admission
                }):
                if prior not in (None,digest) or not remote_ok:
                    try:publish(out,accepted)
                    except (ValueError,RuntimeError):pass
                    else:raise AssertionError("registry divergence accepted")
                    if prior not in (None,digest):
                        assert not calls,"tag reassign attempted"
                else:
                    result=publish(out,accepted)
                    assert result["state"]=="BUILD_ADMITTED"
                    assert result["publication"]=="GHCR_DIGEST_CONFIRMED"
                    assert len(calls)==(0 if prior==digest else 1)
        run_case(None,digest)
        run_case(digest,digest)
        run_case("sha256:"+"1"*64,digest)
        run_case(None,digest,remote_ok=False)
    print(json.dumps({"schema":"qwen-ghcr-publication-offline-critic/v1",
      "state":"PASS","negative_contexts":5,"negative_digests":3,"negative_registry_actors":5,"synthetic_publication_cases":4,
      "publication":"NOT_PERFORMED","real_registry":"NOT_CONTACTED"},sort_keys=True))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("self-test","publish","sync-dle"))
    p.add_argument("--receipt",type=Path)
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    if args.action=="self-test":
        selftest();return
    if args.action=="sync-dle":
        if not args.receipt:p.error("--receipt required for sync-dle")
        record=json.loads(args.receipt.read_text(encoding="utf-8"))
        print(json.dumps(sync_dle(record,dict(os.environ)),sort_keys=True))
        return
    if not args.output:p.error("--output required for publish")
    out=args.output.resolve()
    # Do not write stdout containing raw registry credentials or errors.
    print(json.dumps(publish(out,dict(os.environ)),sort_keys=True))

if __name__=="__main__":main()
