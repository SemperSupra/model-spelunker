#!/usr/bin/env python3
"""Pinned Qwen Code upstream prompt/permission source audit.

This is an offline source identity/contract check, NOT an entitlement to
override safety controls, and not proof that a live model follows instructions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
REQUIRED={
 "packages/core/src/core/prompts.ts":(
    "export function loadCoreSystemPromptSource()",
    "process.env['QWEN_SYSTEM_MD']",
    "const basePrompt = systemMdEnabled",
    "? promptSource.systemPrompt!",
    ": buildDefaultBasePrompt(",
    "return assembleSystemPrompt({",
 ),
 "packages/core/src/config/config.ts":(
    "getSystemPrompt(): string | undefined",
    "coreTools?: string[]",
    "visibleTools?: string[]",
    "eagerTools?: string[]",
 ),
 "packages/cli/src/config/config.ts":(
    "systemPrompt: argv.systemPrompt",
    "appendSystemPrompt: argv.appendSystemPrompt",
    "argv.coreTools || settings.tools?.core",
    "settings.tools?.eager",
    "tools.core",
    "coreToolsAllowList",
 ),
 "packages/cli/src/config/settingsSchema.ts":(
    "coreTools",
    "eager",
    "toolSearch",
 )
}
RUNNER_REQUIRED=(
    "export QWEN_SYSTEM_MD=",
    "export QWEN_WRITE_SYSTEM_MD=0",
    "--core-tools read_file",
    '"tools":{"core":["read_file"],"eager":["read_file"]}',
    "proxy-metadata.json",
    "sse_tool_delta_events",
    "hidden_fixture_oracle",
)


def git_blob_sha(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\x00"+data).hexdigest()


def source_check(pins,files,runner):
    if pins.get("schema")!="qwen-v0.28.3-upstream-source/v1":
        raise ValueError("upstream contract schema mismatch")
    if pins.get("repository")!="QwenLM/qwen-code" or pins.get("version")!="v0.28.3":
        raise ValueError("unexpected upstream project or floating release")
    if pins.get("commit")!="99fcf89892f1a3a8027c75468546c7e7be906245":
        raise ValueError("tag commit mismatch")
    if set(pins.get("files",{}))!=set(REQUIRED):
        raise ValueError("missing or extra source")
    for path,needles in REQUIRED.items():
        raw=files[path]
        if git_blob_sha(raw)!=pins["files"][path]:
            raise ValueError(f"unverified Qwen source: {path}")
        source=raw.decode("utf-8")
        for marker in needles:
            if marker not in source:
                raise ValueError(f"missing upstream prompt/permission signal: {path}:{marker}")
    for marker in RUNNER_REQUIRED:
        if marker not in runner:
            raise ValueError(f"local runner missing strict synthetic control: {marker}")
    if "QWEN_SYSTEM_MD" not in files["packages/core/src/core/prompts.ts"].decode("utf-8"):
        raise ValueError("no full system prompt override")
    if "QWEN_SYSTEM_IDENTITY_MD" not in files["packages/core/src/core/prompts.ts"].decode("utf-8"):
        raise ValueError("no separate identity-only override")
    if '--approval-mode yolo' in runner and '--core-tools read_file' not in runner:
        raise ValueError("public runner ambient effect grant without narrow tool allowlist")
    return {
        "schema":"qwen-r7-upstream-audit/v1",
        "result":"PASS_SOURCE_IDENTITY_AND_INTENT",
        "release":"v0.28.3",
        "upstream_commit":pins["commit"],
        "verified_blob_count":len(REQUIRED),
        "override":"FULL_BASE_SYSTEM_PROMPT_WHEN_QWEN_SYSTEM_MD_FILE",
        "identity_override":"IDENTITY_ONLY_NOT_FULL_PROMPT",
        "core_tools":"EXPLICIT_NARROW_ALLOWLIST",
        "eager_tools":"SCHEMA_DEFERRAL_NOT_AUTHORIZATION",
        "model_runtime":"NOT_TESTED_BY_STATIC_AUDIT",
        "signed_admission":"NOT_GRANTED"
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--upstream",type=Path,required=True)
    parser.add_argument("--pins",type=Path,default=HERE/"source-pins.json")
    parser.add_argument("--runner",type=Path,default=HERE/"run_lean_native.sh")
    p=parser.parse_args()
    pins=json.loads(p.pins.read_text())
    files={path:(p.upstream/path).read_bytes() for path in REQUIRED}
    receipt=source_check(pins,files,p.runner.read_text())
    print(json.dumps(receipt,sort_keys=True))


if __name__=="__main__":
    main()
