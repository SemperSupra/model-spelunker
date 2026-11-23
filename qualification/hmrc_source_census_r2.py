#!/usr/bin/env python3
"""Issue #306 exact-source/manifest bake-off for memory infrastructure candidates.

Public source-only G0. Native backend, agent or model execution are deliberately
NOT claimed. Uses Git blob SHA validation on explicitly pinned upstream files
rather than mutable main or untrusted metadata; no credentials or local hosts.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib
import urllib.request

CANDIDATES={
    "engram":{
        "repo":"Gentleman-Programming/engram",
        "commit":"380d513841f0cc96f87088b837156d758bd1ee4c",
        "license":"MIT",
        "files":{"LICENSE":"5fac9d86f341b8b16cd2bbf6f76a503d9cf26ac8",
                 "go.mod":"56c4c25ad2a387527e9e673792f6ff436150e452"},
    },
    "reme":{
        "repo":"agentscope-ai/ReMe",
        "commit":"54fa3381d7fec4cdabb1b4092f5e755d7f62c769",
        "license":"Apache-2.0",
        "files":{"LICENSE":"65c2c5cf06d722c79d8105cfce97016491a7a7f4",
                 "pyproject.toml":"4195326acd013e4f6f6927c48d836ad305935ff4"},
    },
    "openviking":{
        "repo":"volcengine/OpenViking",
        "commit":"aa885b902075e17b13756266049de3c21ac4ae43",
        "license":"AGPL-3.0",
        "files":{"LICENSE":"27268c8e4ad8c300f7665fe6b20875c580d05f4b",
                 "pyproject.toml":"80cfe0ca61881e3039364960de2749a76014a365"},
    },
    "memos":{
        "repo":"MemTensor/MemOS",
        "commit":"3a16e5fe3048a209f722806f4123fa2e533588fd",
        "license":"Apache-2.0",
        "files":{"LICENSE":"2090de541d3389f3da3d001d37e6426fe5c93779",
                 "pyproject.toml":"134d380eefc7198aecd79739836c13233c9016ea"},
    },
}

def git_blob(data:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\x00"+data).hexdigest()

def checked_file(body:bytes, expected:str)->bytes:
    if git_blob(body)!=expected:
        raise ValueError("upstream file blob drift; reject mutable or tampered source")
    if len(body)>200_000:
        raise ValueError("unexpectedly oversized public source manifest")
    return body

def read_url(repo:str,commit:str,path:str)->bytes:
    if not re.fullmatch(r"[0-9a-f]{40}",commit) or path not in ("LICENSE","go.mod","pyproject.toml"):
        raise ValueError("unsupported upstream source request")
    req=urllib.request.Request(f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                               headers={"User-Agent":"hmrc-public-source-census-r2"})
    with urllib.request.urlopen(req,timeout=35) as response:
        content=response.read(200_001)
        if response.status!=200:
            raise ValueError("upstream file fetch not successful")
        return content

def classify_license(raw:str)->str:
    head=raw[:1000]
    if "GNU AFFERO GENERAL PUBLIC LICENSE" in head:return "AGPL-3.0"
    if "Apache License" in head and "Version 2.0" in head:return "Apache-2.0"
    if "MIT License" in head:return "MIT"
    return "UNKNOWN"

def manifest_report(name:str,files:dict[str,bytes])->dict:
    expected=CANDIDATES[name]
    license_name=classify_license(files["LICENSE"].decode())
    if license_name!=expected["license"]:
        raise ValueError("declared license inconsistent with pinned LICENSE file")
    row={"candidate":name,"repo":expected["repo"],"commit":expected["commit"],
         "license":license_name,"source_pinned":True,
         "blobs":dict(expected["files"]),"source_only":True,
         "installed":False,"native_memory_executed":False,
         "model_inference_executed":False,"harness_task_accepted":False,
         "physical_kv_controller_executed":False,
         "transitive_license_clearance":"UNKNOWN",
         "production_admission":"NOT_EVALUATED"}
    if "pyproject.toml" in files:
        project=tomllib.loads(files["pyproject.toml"].decode())
        metadata=project.get("project",{})
        license_meta=metadata.get("license")
        if isinstance(license_meta,dict):license_meta=license_meta.get("text")
        if license_meta != license_name:
            raise ValueError("manifest license does not agree with LICENSE")
        row.update({
            "runtime":"python",
            "project_name":metadata.get("name"),
            "minimum_python":metadata.get("requires-python","UNKNOWN"),
            "direct_dependency_declarations":len(metadata.get("dependencies",[])),
            "optional_extras":len(metadata.get("optional-dependencies",{})),
            "build_requirements":project.get("build-system",{}).get("requires",[]),
            "declared_version":metadata.get("version","DYNAMIC"),
        })
    else:
        data=files["go.mod"].decode()
        m=re.search(r"(?m)^go\s+([0-9.]+)",data)
        if not m:raise ValueError("no Go version declared")
        rows=re.findall(r"(?m)^\s*([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)\s+v[0-9]",data)
        row.update({"runtime":"go","project_name":re.search(r"(?m)^module\s+(.+)",data).group(1),
                    "minimum_go":m.group(1),"dependency_declarations":len(rows),
                    "build_requirements":[]})
    row["license_integration_gate"]="manual AGPL network-use/license compliance review" if license_name=="AGPL-3.0" else "transitive-license and compatibility review"
    return row

def self_test()->None:
    for name,c in CANDIDATES.items():
        assert re.fullmatch(r"[0-9a-f]{40}",c["commit"])
        for path,sha in c["files"].items():
            assert path in ("LICENSE","go.mod","pyproject.toml")
            assert re.fullmatch(r"[0-9a-f]{40}",sha)
    assert classify_license("MIT License\n")=="MIT"
    assert classify_license("Apache License\nVersion 2.0")=="Apache-2.0"
    assert classify_license("GNU AFFERO GENERAL PUBLIC LICENSE")=="AGPL-3.0"
    assert git_blob(b"hello")=="b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"
    try:checked_file(b"tampered","0"*40)
    except ValueError:pass
    else:raise AssertionError("source hash fail-open")
    print("PASS exact upstream source pins and blob hash negative controls; backend NOT_RUN")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--backend",choices=CANDIDATES)
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--out",type=Path)
    a=p.parse_args()
    if a.self_test:self_test();return
    if not a.backend or not a.out:p.error("--backend and --out required")
    profile=CANDIDATES[a.backend]
    files={}
    for path,sha in profile["files"].items():
        content=checked_file(read_url(profile["repo"],profile["commit"],path),sha)
        files[path]=content
    result=manifest_report(a.backend,files)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("SOURCE_PINNED_CANDIDATE="+json.dumps(result,sort_keys=True))
    print("NATIVE_BACKEND=NOT_RUN; MODEL=NOT_RUN; AGPL_COMPLIANCE_REVIEW_REQUIRED="+str(result["license"]=="AGPL-3.0"))

if __name__=="__main__":main()
