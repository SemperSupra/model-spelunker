#!/usr/bin/env python3
"""Public source-bound agent framework refresh census (NO install or publishing).

Observe official GitHub releases/commits; output only an allowlisted public
source/version matrix. Unverified upstream metadata is never a release admission.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[2]
UA="model-spelunker-public-harness-census/1"
BASE="https://api.github.com/repos/"
SUBJECTS=(
  {"id":"openworker","repo":"andrewyng/openworker","upstream":"head",
   "baseline_version":None,"baseline_sha":"5bc10d928e0b64aae74313349a3b17bd19643ae2",
   "admission":"qualification/harness-artifacts/openworker-5bc10d928e0b-linux-x64.admission-v2.json",
   "realization":"qualification/harness-realizations/openworker-linux-amd64-sovereign-python-abi-v1.json",
   "class":"BUILT_GHCR"},
  {"id":"goose","repo":"aaif-goose/goose","upstream":"stable_release",
   "baseline_version":"1.55.0","baseline_sha":None,
   "admission":"qualification/harness-artifacts/goose-1.55.0-linux-x64-glibc236.admission.json",
   "realization":"qualification/harness-realizations/goose-linux-amd64-glibc236-v1.json",
   "class":"BUILT_GHCR"},
  {"id":"codex-exec","repo":"openai/codex","upstream":"stable_release",
   "baseline_version":"0.154.0","baseline_sha":"6b9826e3aa83b1a5947db50f4332cb9c65f1b340",
   "admission":"qualification/harness-artifacts/codex-exec-6b9826e3aa83-linux-x64.admission.json",
   "realization":None,"class":"BUILT_GHCR"},
  {"id":"qwen-code","repo":"QwenLM/qwen-code","upstream":"stable_release",
   "baseline_version":"0.28.3","baseline_sha":None,
   "admission":"qualification/qwencode_public/release-manifest.json",
   "realization":"qualification/agent_embodiment/qwen-public-linux.json",
   "class":"BUILT_GHCR"},
  {"id":"opencode","repo":"anomalyco/opencode","upstream":"major2_release",
   "baseline_version":None,"baseline_sha":None,"admission":None,
   "realization":None,"class":"CANDIDATE_NOT_BUILT"},
  {"id":"pi","repo":"earendil-works/pi-mono","upstream":"stable_release",
   "baseline_version":None,"baseline_sha":None,"admission":None,
   "realization":None,"class":"CANDIDATE_NOT_BUILT"},
  {"id":"aider","repo":"Aider-AI/aider","upstream":"stable_release",
   "baseline_version":None,"baseline_sha":None,"admission":None,
   "realization":None,"class":"CANDIDATE_NOT_BUILT"}
)
def expect_subjects():
    ids=[v["id"] for v in SUBJECTS]
    if len(set(ids))!=len(ids):raise ValueError("duplicate harness")
    for v in SUBJECTS:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",v["repo"]):
            raise ValueError("unsafe repository name")
        if v["admission"] and not (ROOT/v["admission"]).is_file():
            raise ValueError("missing prior artifact evidence "+v["admission"])
        if v["realization"] and not (ROOT/v["realization"]).is_file():
            raise ValueError("missing realization "+v["realization"])
        if v["baseline_sha"] and not re.fullmatch("[a-f0-9]{40}",v["baseline_sha"]):
            raise ValueError("invalid pinned source hash")
        if v["class"]=="BUILT_GHCR" and not v["admission"]:
            raise ValueError("unproven original package")
def fetch_json(url: str, max_bytes:int=2_000_000):
    if not url.startswith(BASE):raise ValueError("disallowed API URL")
    req=urllib.request.Request(url,headers={
        "User-Agent":UA,"Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28"})
    with urllib.request.urlopen(req,timeout=25) as response:
        if response.status!=200:raise ValueError("upstream non-200")
        data=response.read(max_bytes+1)
        if len(data)>max_bytes:raise ValueError("oversize upstream JSON")
        obj=json.loads(data.decode("utf-8"))
        return obj
def tag_version(tag: str) -> tuple[int,...] | None:
    m=re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)",tag)
    if not m:return None
    return tuple(int(v) for v in m.groups())
def choose_release(releases:list, mode:str) -> dict:
    if not isinstance(releases,list):raise ValueError("bad release list")
    candidates=[]
    for r in releases:
        if not isinstance(r,dict) or r.get("draft") or r.get("prerelease"):continue
        tag=r.get("tag_name")
        if not isinstance(tag,str):continue
        version=tag_version(tag)
        if version is None:continue
        if mode=="major2_release" and version[0]!=2:continue
        candidates.append((version,r))
    if not candidates:raise ValueError("no stable release matching mode")
    return max(candidates,key=lambda pair:pair[0])[1]
def redacted_release(release:dict,sha:str) -> dict:
    tag=release.get("tag_name")
    version=tag_version(tag)
    if version is None:raise ValueError("non-semver release cannot automatically update")
    if not re.fullmatch("[a-f0-9]{40}",sha):raise ValueError("unverified release commit")
    assets=release.get("assets",[])
    if not isinstance(assets,list):raise ValueError("bad release assets")
    rows=[]
    for a in assets[:200]:
        name=a.get("name","")
        digest=a.get("digest")
        if not isinstance(name,str) or not re.fullmatch(r"[A-Za-z0-9_.+()-]{1,160}",name):continue
        if not isinstance(digest,str) or not re.fullmatch(r"sha256:[a-f0-9]{64}",digest):
            digest=None
        rows.append({"name":name,"sha256":digest,
                     "bytes":a.get("size") if isinstance(a.get("size"),int) else None})
    return {"tag":tag,"version":".".join(map(str,version)),"source_commit":sha,
            "published_at":release.get("published_at") if isinstance(release.get("published_at"),str) else None,
            "release_assets":rows,"release_asset_sha_coverage":sum(1 for a in rows if a["sha256"])}
def classification(subject:dict,current:dict)->str:
    if current["source_commit"] is None:return "UNVERIFIED"
    if subject["upstream"]=="head":
        return "SAME_UPSTREAM_COMMIT" if current["source_commit"]==subject["baseline_sha"] else "UPDATE_CANDIDATE_UNVERSIONED"
    if subject["class"]!="BUILT_GHCR":return "NOT_PREVIOUSLY_BUILT"
    old=tag_version(subject["baseline_version"])
    new=tag_version(current["tag"])
    if new is None:return "UNVERIFIED"
    if new>old:return "UPDATE_CANDIDATE"
    if new==old:return "BASELINE_VERSION_CURRENT"
    return "UPSTREAM_BEHIND_BASELINE"
def observe(subject:dict)->dict:
    base=BASE+subject["repo"]+"/"
    try:
        if subject["upstream"]=="head":
            metadata=fetch_json(base+"commits/HEAD")
            sha=metadata.get("sha")
            if not isinstance(sha,str) or not re.fullmatch("[a-f0-9]{40}",sha):
                raise ValueError("unverified upstream HEAD")
            current={"tag":None,"version":None,"source_commit":sha,"published_at":None,
                     "release_assets":[],"release_asset_sha_coverage":0}
        else:
            if subject["upstream"]=="major2_release":
                release=choose_release(fetch_json(base+"releases?per_page=30"),subject["upstream"])
            else:
                release=fetch_json(base+"releases/latest")
            tag=release.get("tag_name","")
            if not isinstance(tag,str) or not re.fullmatch("[A-Za-z0-9_.-]{1,128}",tag):
                raise ValueError("release tag absent/unsafe")
            commit=fetch_json(base+"commits/"+tag)
            current=redacted_release(release,commit.get("sha",""))
        status=classification(subject,current)
    except (ValueError,KeyError,urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as e:
        current={"tag":None,"version":None,"source_commit":None,"published_at":None,
                 "release_assets":[],"release_asset_sha_coverage":0}
        status="UNAVAILABLE_OR_UNVERIFIED"
    return {"id":subject["id"],"official_repo":subject["repo"],
            "previous_class":subject["class"],"baseline_version":subject["baseline_version"],
            "baseline_source_sha":subject["baseline_sha"],
            "baseline_admission_ref":subject["admission"],
            "baseline_realization_ref":subject["realization"],
            "upstream_selection":subject["upstream"],
            "observed_upstream":current,"status":status,
            "artifact_admission":"NOT_PERFORMED",
            "config_migration":"NOT_PERFORMED",
            "runtime_task_qualification":"NOT_PERFORMED",
            "protected_ghcr_publish":"NOT_PERFORMED"}
def selftest():
    expect_subjects()
    versions=[{"tag_name":"v1.1.0","draft":False,"prerelease":False},
      {"tag_name":"v2.3.0","draft":False,"prerelease":False},
      {"tag_name":"v2.4.0-alpha.1","draft":False,"prerelease":True},
      {"tag_name":"v2.2.9","draft":True,"prerelease":False},
      {"tag_name":"v2.2.0","draft":False,"prerelease":False}]
    assert choose_release(versions,"major2_release")["tag_name"]=="v2.3.0"
    assert tag_version("v0.154.0")==(0,154,0)
    assert tag_version("v1.0.0-rc1") is None
    fake={"source_commit":"a"*40,"tag":"v1.55.0"}
    assert classification({**SUBJECTS[1],"baseline_version":"1.55.0"},fake)=="BASELINE_VERSION_CURRENT"
    fake["tag"]="v1.56.0"
    assert classification(SUBJECTS[1],fake)=="UPDATE_CANDIDATE"
    fake["tag"]="v1.54.9"
    assert classification(SUBJECTS[1],fake)=="UPSTREAM_BEHIND_BASELINE"
    try:fetch_json("https://example.invalid")
    except ValueError:pass
    else:raise AssertionError("unrestricted API URL accepted")
    print(json.dumps({"schema":"agent-fleet-release-census-critic/v1",
       "verdict":"PASS","previously_admitted":sum(x["class"]=="BUILT_GHCR" for x in SUBJECTS),
       "unbuilt_candidates":sum(x["class"]!="BUILT_GHCR" for x in SUBJECTS),
       "negative_controls":5,"network":"NOT_CONTACTED"},sort_keys=True))
def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("self-test","observe"))
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    if a.action=="self-test":selftest();return
    expect_subjects()
    if a.output is None:p.error("--output required")
    result={"schema":"agent-fleet-source-refresh-census/v1",
       "authority":"SOURCE_ONLY_PUBLIC_METADATA","auto_upgrade":False,
       "production_admission":"NOT_GRANTED","registry_write":"NOT_PERFORMED",
       "current_is_observed_not_pinned":True,
       "subjects":[observe(x) for x in SUBJECTS]}
    a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":result["schema"],"authority":result["authority"],
       "subjects":[{"id":x["id"],"status":x["status"],
                    "current_version":x["observed_upstream"]["version"],
                    "source_sha":x["observed_upstream"]["source_commit"]} for x in result["subjects"]]},sort_keys=True))
if __name__=="__main__":main()
