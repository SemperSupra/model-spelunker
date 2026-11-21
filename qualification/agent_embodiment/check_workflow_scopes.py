#!/usr/bin/env python3
"""Scope expensive Qwen qualification workflows to actual source dependencies.

Offline stdlib checks. This is not a general YAML parser or release authority.
A changed workflow YAML is tested by this lightweight critic, while real
model/OCI jobs run when their actual harness/config/build inputs change.
"""
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SCOPES={
".github/workflows/qwen-r18-native-use.yml":[
 "qualification/agent_embodiment/qwen_embody.py",
 "qualification/agent_embodiment/qwen-public-linux.json",
 "qualification/agent_embodiment/run_native_installed.sh",
 "qualification/agent_embodiment/final_oracle.py",
 "qualification/agent_embodiment/lineage_oracle.py",
 "qualification/agent_embodiment/settings_drift.py",
 "qualification/qwencode_public/kit.py",
 "qualification/qwencode_public/release-manifest.json"
],
".github/workflows/qwen-r18-embodiment.yml":[
 "qualification/agent_embodiment/qwen_embody.py",
 "qualification/agent_embodiment/qwen-public-linux.json",
 "qualification/qwencode_public/kit.py",
 "qualification/qwencode_public/release-manifest.json"
],
".github/workflows/qwen-r19-oci-carrier.yml":[
 "qualification/agent_embodiment/qwen_oci.py",
 "qualification/agent_embodiment/qwen_embody.py",
 "qualification/agent_embodiment/qwen-public-linux.json",
 "qualification/qwencode_public/kit.py",
 "qualification/qwencode_public/release-manifest.json",
 "qualification/package_artifact_oci.py",
 "qualification/hydrate_oci_layout.py"
]}

def extract_paths(raw: str) -> list[str]:
    lines=raw.splitlines()
    try:
        pos=lines.index("on:")
        assert lines[pos+1]=="  pull_request:"
        assert lines[pos+2]=="    paths:"
    except (ValueError,IndexError,AssertionError) as exc:
        raise ValueError("noncanonical workflow event/paths") from exc
    paths=[]
    for line in lines[pos+3:]:
        if not line.startswith("      - "):break
        expression=line.removeprefix("      - ")
        try:path=ast.literal_eval(expression)
        except (SyntaxError,ValueError) as exc:
            raise ValueError("invalid workflow path item") from exc
        if not isinstance(path,str) or not path:
            raise ValueError("invalid path")
        paths.append(path)
    if not paths or len(paths)!=len(set(paths)):
        raise ValueError("empty/duplicated path list")
    if any("*" in p or "!" in p or "?" in p for p in paths):
        raise ValueError("broad or negative workflow pattern")
    if not any(line=="permissions:" for line in lines):
        raise ValueError("missing explicit job permissions")
    return paths

def verify():
    rows={}
    for name,expected in SCOPES.items():
        data=(ROOT/name).read_text(encoding="utf-8")
        actual=extract_paths(data)
        if set(actual)!=set(expected):
            raise ValueError("workflow source dependency mismatch: "+name)
        for path in actual:
            if not (ROOT/path).is_file():
                raise ValueError("workflow references missing code source: "+path)
        rows[name.split("/")[-1]]=len(actual)
    return rows

def selftest():
    template="on:\n  pull_request:\n    paths:\n      - 'a/b.py'\npermissions:\n  contents: read\n"
    assert extract_paths(template)==["a/b.py"]
    for mutated in (
        template.replace("'a/b.py'","'a/**'"),
        template.replace("      - 'a/b.py'","      - 'a/b.py'\n      - 'a/b.py'"),
        template.replace("  pull_request:","  push:"),
        template.replace("permissions:","no-permissions:")):
        try:extract_paths(mutated)
        except ValueError:pass
        else:raise AssertionError("incorrect workflow path accepted")
    print(json.dumps({"schema":"qwen-workflow-scope-critic/v1",
      "state":"PASS","negative_scope_mutants":4,"scoped_workflows":verify()},sort_keys=True))
if __name__=="__main__":selftest()
