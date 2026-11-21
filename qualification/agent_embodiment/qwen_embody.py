#!/usr/bin/env python3
"""Public synthetic Qwen workcell: plan -> stage -> verify -> remove.

No production admission. This implementation deliberately operates ONLY inside a
disposable public GitHub Actions RUNNER_TEMP directory. Other embodiments must
have independently authorized applicators; never extend this safety boundary by
an env-var switch on a persistent host.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"qwencode_public"))
import kit  # pinned official release verifier, no global install

PROFILE=HERE/"qwen-public-linux.json"
MARKER=".agent-embodiment-owner.json"

def canonical(obj: dict) -> bytes:
    return (json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=True)+"\n").encode()

def fail(why: str):
    raise ValueError(why)

def validate_profile(p: dict) -> dict:
    if p.get("schema")!="agent-embodiment-profile/v1":fail("profile schema")
    identity=p.get("identity",{})
    if (identity.get("framework"),identity.get("framework_version"),identity.get("embodiment"),
        identity.get("classification"),identity.get("authority"))!=(
        "qwen-code","0.28.3","disposable-linux-x64","public-synthetic","NO_PRODUCTION_ADMISSION"):
        fail("identity is not an authorized public synthetic fixture")
    manifest=kit.load_manifest()
    if manifest["version"]!=identity["framework_version"]:fail("version drift")
    if p.get("artifact",{}).get("platform")!="linux-x64":fail("platform not qualified")
    if p["artifact"].get("manifest")!="qualification/qwencode_public/release-manifest.json":fail("release origin changed")
    model=p.get("model",{})
    if (model.get("provider"),model.get("model"),model.get("base_url"),
        model.get("context_window"),model.get("max_output_tokens"),
        model.get("env_key"),model.get("reasoning_effort"))!=(
        "ollama-openai-compatible","qwen3:1.7b","http://127.0.0.1:11434/v1",
        32768,256,"OLLAMA_API_KEY","none"):
        fail("unadmitted model, remote endpoint or context/output boundary")
    if (p.get("tools",{}).get("allowlist"),p["tools"].get("mcp_servers"),
        p["tools"].get("approval_mode"))!=(["read_file"],{},"default"):fail("tools authority changed")
    if p.get("memory")!={"managed_auto_memory":False,"managed_auto_dream":False,"team_memory":False}:fail("memory authority changed")
    workcell=p.get("workcell",{})
    if workcell!={"root_kind":"runner-temp","network_scope":"loopback-only",
                 "credential_source":"environment-reference","self_authorize":False,
                 "retention":"ephemeral","external_admission_required":True}:
        fail("workcell isolation contract changed")
    return p

def load_profile() -> dict:
    return validate_profile(json.loads(PROFILE.read_text(encoding="utf-8")))

def settings(profile: dict) -> dict:
    m=profile["model"]
    # Source pinned Qwen Code v0.28.3: packages/cli/src/config/settings.ts
    # SETTINGS_VERSION=4, SETTINGS_VERSION_KEY='$version'.
    # Preseed version so the CLI does not rewrite its owned settings on startup.
    return {
      "$version":4,
      "security":{"auth":{"selectedType":"openai"}},
      "model":{"name":m["model"]},
      "modelProviders":{"openai":[{
        "id":m["model"],"envKey":m["env_key"],"baseUrl":m["base_url"],
        "generationConfig":{
          "timeout":140000,"maxRetries":0,"contextWindowSize":m["context_window"],
          "samplingParams":{"temperature":0,"max_tokens":m["max_output_tokens"],
                            "reasoning_effort":m["reasoning_effort"]}
        }
      }]},
      "tools":{"core":["read_file"],"eager":["read_file"],"toolSearch":{"enabled":False}},
      "memory":{"enableManagedAutoMemory":False,"enableManagedAutoDream":False,
                "enableTeamMemory":False,"enableTeamMemorySync":False},
      "experimental":{"agentTeam":False},"mcpServers":{},
      "privacy":{"usageStatisticsEnabled":False}
    }

def specification(profile: dict) -> dict:
    manifest=kit.load_manifest()
    return {
        "schema":"agent-embodiment-plan/v1",
        "authority":"NO_PRODUCTION_ADMISSION",
        "framework":"qwen-code","version":manifest["version"],"platform":"linux-x64",
        "release_sha256":manifest["platforms"]["linux-x64"]["sha256"],
        "profile_sha256":hashlib.sha256(canonical(profile)).hexdigest(),
        "settings_sha256":hashlib.sha256(canonical(settings(profile))).hexdigest(),
        "mutations":["owned-workcell/archive-extract","owned-workcell/home/.qwen/settings.json"],
        "requires_external_admission":True,
        "candidate_only":True
    }

def workcell_root(root: Path) -> Path:
    # Runtime/env checks are operational guardrails, NOT trusted runner attestation.
    # Never reuse this synthetic applicator on an owner host by setting env vars.
    if os.environ.get("GITHUB_ACTIONS")!="true":fail("only disposable GitHub Actions synthetic apply/verify/remove supported")
    temp=os.environ.get("RUNNER_TEMP")
    if not temp:fail("RUNNER_TEMP absent")
    base=Path(temp).resolve(strict=True)
    path=root.resolve()
    if not path.is_relative_to(base) or path==base:fail("workcell outside RUNNER_TEMP")
    if root.is_symlink():fail("root symlink forbidden")
    for parent in (root,*root.parents):
        if parent==base:break
        if parent.is_symlink():fail("symlink parent forbidden")
    return path

def installed_files(root: Path) -> list[dict]:
    """Bounded, strict byte inventory for extracted upstream runtime.

    The expected manifest is recorded at stage and must match subsequent verify.
    This protects against accidental payload drift; a writable ownership marker
    is NOT cryptographic admission/attestation against a malicious same-user actor.
    """
    base=root/"native"
    if base.is_symlink() or not base.is_dir():
        fail("native runtime missing or symlink")
    result=[]
    for index,path in enumerate(sorted(base.rglob("*"))):
        if index >= 16000:
            fail("unbounded native artifact")
        if path.is_symlink():
            fail("native artifact symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            fail("native artifact non-regular entry")
        result.append({"path":path.relative_to(root).as_posix(),
                       "size":path.stat().st_size,
                       "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    if not result:fail("empty native artifact")
    return result

def owner_record(root: Path, plan: dict) -> dict:
    marker=root/MARKER
    if marker.is_symlink() or not marker.is_file():fail("unowned workcell")
    owner=json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(owner,dict) or owner.get("schema")!="agent-embodiment-owner/v2":
        fail("invalid owner record")
    if owner.get("plan")!=plan:
        fail("workcell plan drift or corrupted owner marker")
    if not isinstance(owner.get("installed_files"),list) or not owner["installed_files"]:
        fail("missing installed file inventory")
    return owner

def evidence(root: Path,plan: dict) -> dict:
    owner=owner_record(root,plan)
    cfg=root/"home/.qwen/settings.json"
    if cfg.is_symlink() or not cfg.is_file():fail("settings missing or symlink")
    # Hash of actual file, not of in-memory object
    if hashlib.sha256(cfg.read_bytes()).hexdigest()!=plan["settings_sha256"]:
        fail("settings differ from plan")
    binary=root/"native/qwen-code/bin/qwen"
    if binary.is_symlink() or not binary.is_file():fail("pinned native binary missing")
    actual_files=installed_files(root)
    if actual_files!=owner["installed_files"]:
        fail("installed native payload drift")
    return {"schema":"agent-embodiment-receipt/v1","status":"VERIFIED",
            "installed_payload_file_count":len(actual_files),
            "installed_payload_integrity":"MATCHES_STAGE_INVENTORY_NOT_SIGNED",
            "source":"PINNED_OFFICIAL_QWEN_0_28_3",
            "profile_sha256":plan["profile_sha256"],
            "settings_sha256":plan["settings_sha256"],
            "artifact_sha256":plan["release_sha256"],
            "model_inference":"NOT_EXECUTED_BY_INSTALLER",
            "operational_admission":"NOT_GRANTED"}

def stage(root: Path,archive: Path,profile: dict,plan: dict) -> dict:
    path=workcell_root(root)
    if path.exists():fail("workcell already exists; never overwrite or adopt")
    # Verify all bytes and archive safety BEFORE creating workcell directories.
    manifest=kit.load_manifest()
    kit.verify(archive,manifest["platforms"]["linux-x64"])
    path.mkdir(parents=False,exist_ok=False)
    try:
        # smoke checks upstream qwen --version, not just extracted file presence
        native=kit.smoke(manifest,"linux-x64",archive,path/"native")
        assert native["native_cli"]=="PASS"
        cfg=path/"home/.qwen/settings.json"
        cfg.parent.mkdir(parents=True,exist_ok=False)
        cfg.write_bytes(canonical(settings(profile)))
        (path/MARKER).write_bytes(canonical({
            "schema":"agent-embodiment-owner/v2",
            "plan":plan,
            "installed_files":installed_files(path)
        }))
        return evidence(path,plan)
    except Exception:
        # The newly created empty-owned path did not preexist; remove partial stage.
        shutil.rmtree(path)
        raise

def remove(root: Path,plan: dict) -> dict:
    path=workcell_root(root)
    # Teardown checks exact original ownership and plan, NOT mutable runtime
    # integrity: a corrupted workcell must remain safely removable.
    # Unowned or modified owner records fail closed and require external
    # workcell controller quarantine; never delete an adopted/unknown path.
    owner_record(path,plan)
    shutil.rmtree(path)
    if path.exists():fail("owned teardown incomplete")
    return {"schema":"agent-embodiment-receipt/v1","status":"REMOVED",
            "profile_sha256":plan["profile_sha256"],"operational_admission":"NOT_GRANTED",
            "teardown_authority":"MATCHED_OWNER_RECORD_ONLY"}

def synthetic_tests(profile: dict,plan: dict):
    """Mutation tests MUST invoke the real validation function and see refusal."""
    import copy
    tests = [
        ("model_base", lambda p:p["model"].update(base_url="https://example.invalid/v1")),
        ("model_context", lambda p:p["model"].update(context_window=2048)),
        ("model_budget", lambda p:p["model"].update(max_output_tokens=1)),
        ("tools", lambda p:p["tools"].update(allowlist=["run_shell_command"])),
        ("mcp", lambda p:p["tools"].update(mcp_servers={"injected":{}})),
        ("memory", lambda p:p["memory"].update(team_memory=True)),
        ("workcell", lambda p:p["workcell"].update(root_kind="persistent-host")),
        ("authority", lambda p:p["identity"].update(authority="PRODUCTION")),
        ("platform", lambda p:p["artifact"].update(platform="windows-x64")),
        ("credential", lambda p:p["model"].update(env_key="ACTUAL_TOKEN_VALUE")),
    ]
    assert validate_profile(copy.deepcopy(profile))==profile
    for name,change in tests:
        mutated=copy.deepcopy(profile)
        change(mutated)
        try:
            validate_profile(mutated)
        except (ValueError,AssertionError,KeyError,TypeError):
            continue
        raise AssertionError("unsafe profile mutant accepted: "+name)
    assert plan["requires_external_admission"] and plan["candidate_only"]
    assert settings(profile)["$version"]==4
    print(json.dumps({"schema":"agent-embodiment-contract-selftest/v2",
        "status":"PASS","negative_profile_mutants":len(tests),
        "scope":"OFFLINE_SOURCE_ONLY","production_admission":"DENIED"},sort_keys=True))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("action",choices=("self-test","plan","stage","verify","remove"))
    ap.add_argument("--root",type=Path)
    ap.add_argument("--archive",type=Path)
    args=ap.parse_args()
    profile=load_profile()
    plan=specification(profile)
    if args.action=="self-test":
        synthetic_tests(profile,plan)
        return
    if args.action=="plan":
        print(json.dumps(plan,sort_keys=True))
        return
    if not args.root:ap.error("root required for stage/verify/remove")
    if args.action=="stage":
        if not args.archive:ap.error("archive required for stage")
        receipt=stage(args.root,args.archive,profile,plan)
    elif args.action=="verify":
        receipt=evidence(workcell_root(args.root),plan)
    else:
        receipt=remove(args.root,plan)
    print(json.dumps(receipt,sort_keys=True))
if __name__=="__main__":main()
