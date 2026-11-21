#!/usr/bin/env python3
"""Public-safe external GitHub Actions receipt verifier (R6-A).

This is read-only and deliberately *not* a scheduler/admission source. It checks
remote GitHub Actions run+job identity/conclusions for the exact completed
source-neutral batch ledger, not the truth of model/hardware semantic claims.
No token, private repository, host URL, artifact contents or write API.
"""
import argparse
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
import sys

HERE=Path(__file__).resolve().parent
EXPECTED_REPO="SemperSupra/model-spelunker"
ROOT="https://api.github.com/repos/SemperSupra/model-spelunker/actions/runs/"
WEB_RE=re.compile(r"^https://github\.com/SemperSupra/model-spelunker/actions/runs/([1-9][0-9]{6,16})$")
SHA_RE=re.compile(r"^[0-9a-f]{40}$")
VALID_STATES=("DONE_VERIFIED","FAILED")
MAX_RESPONSE_BYTES=1_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("GitHub API redirect refused")


def live_get(url):
    if not url.startswith(ROOT):
        raise ValueError("non-allowlisted GitHub API endpoint")
    tail=url[len(ROOT):]
    if not re.fullmatch(r"[1-9][0-9]{6,16}(/jobs\?per_page=100)?",tail):
        raise ValueError("unsupported GitHub API path")
    opener=urllib.request.build_opener(NoRedirect())
    req=urllib.request.Request(url,headers={"User-Agent":"public-qwen-receipt-verifier/1",
                                           "Accept":"application/vnd.github+json",
                                           "X-GitHub-Api-Version":"2022-11-28"},
                               method="GET")
    with opener.open(req,timeout=9) as resp:
        if resp.status!=200:
            raise ValueError("GitHub REST unexpected HTTP status")
        data=resp.read(MAX_RESPONSE_BYTES+1)
        if len(data)>MAX_RESPONSE_BYTES:
            raise ValueError("oversize GitHub response")
        return json.loads(data)


def validate_ledger(doc,expected):
    if doc.get("schema")!="qwen-independent-batches/v1":
        raise ValueError("wrong ledger schema")
    if doc.get("dispatcher")!="AGENT_DISPATCH_ONLY":
        raise ValueError("unexpected dispatch authority")
    if not isinstance(doc.get("tasks"),list):
        raise ValueError("missing packet list")
    if expected.get("schema")!="qwen-public-receipt-job-oracles/v1":
        raise ValueError("expected job oracle schema")
    rules=expected.get("rules")
    if not isinstance(rules,dict) or len(rules)!=6:
        raise ValueError("missing oracles")
    targets={}
    for t in doc["tasks"]:
        if t.get("state") not in VALID_STATES:
            continue
        name=t.get("id")
        if name in targets:
            raise ValueError("duplicate verified packet")
        if name not in rules:
            raise ValueError("unverified packet has no external oracle")
        if t.get("repo")!=EXPECTED_REPO:
            raise ValueError("private/repo drift")
        sha=t.get("source_sha")
        if not isinstance(sha,str) or not SHA_RE.fullmatch(sha):
            raise ValueError("bad source revision")
        evidence=t.get("evidence") or {}
        match=WEB_RE.fullmatch(str(evidence.get("run_url","")))
        if not match or evidence.get("source_sha")!=sha:
            raise ValueError("unsafe/bad run reference")
        oracle="PASS" if t["state"]=="DONE_VERIFIED" else "FAIL"
        if evidence.get("independent_oracle")!=oracle:
            raise ValueError("false ledger oracle status")
        rid=int(match.group(1))
        rule=rules[name]
        if rule.get("state")!=t["state"] or rule.get("run_id")!=rid:
            raise ValueError("run/task classification changed without independent review")
        if rule.get("head_sha")!=sha:
            raise ValueError("run source SHA does not match external witness pin")
        jobs=rule.get("jobs")
        if not isinstance(jobs,dict) or not jobs or any(
            v not in ("success","failure") for v in jobs.values()
        ):
            raise ValueError("job gate definition invalid")
        targets[name]={"source_sha":sha,"run_id":rid,"state":t["state"],
                       "expected_run_conclusion":"success" if oracle=="PASS" else "failure",
                       "jobs":jobs}
    if set(targets)!=set(rules):
        raise ValueError("ledger no longer matches reviewed receipt set")
    return targets


def verify_one(name,case,get):
    rid=case["run_id"]
    run=get(ROOT+str(rid))
    if run.get("head_sha")!=case["source_sha"]:
        raise ValueError(f"{name}: GitHub run head does not match source")
    if run.get("status")!="completed" or run.get("conclusion")!=case["expected_run_conclusion"]:
        raise ValueError(f"{name}: GitHub run not complete or conclusion mismatch")
    if run.get("name") is None or run.get("repository",{}).get("full_name")!=EXPECTED_REPO:
        raise ValueError(f"{name}: source repository/workflow metadata missing")
    group=get(ROOT+str(rid)+"/jobs?per_page=100")
    rows=group.get("jobs")
    total=group.get("total_count")
    if not isinstance(total,int) or not isinstance(rows,list) or total!=len(rows):
        raise ValueError(f"{name}: incomplete jobs page")
    if len(rows)>60:
        raise ValueError(f"{name}: oversized job set")
    byname={}
    for job in rows:
        label=job.get("name")
        if not isinstance(label,str) or label in byname:
            raise ValueError(f"{name}: missing/duplicate job name")
        byname[label]=job
    for label,expected_result in case["jobs"].items():
        job=byname.get(label)
        if not job or job.get("status")!="completed" or job.get("conclusion")!=expected_result:
            raise ValueError(f"{name}: required independent job mismatch: {label}")
    return {"packet":name,"status":"VERIFIED_GHA_STATUS_ONLY",
            "source":case["source_sha"],"run_id":rid,
            "workflow_conclusion":run["conclusion"],
            "independent_required_jobs":len(case["jobs"]),
            "semantic_oracle_content":"NOT_REVALIDATED"}


def verify(doc,expected,get):
    targets=validate_ledger(doc,expected)
    details=[verify_one(name,case,get) for name,case in sorted(targets.items())]
    return {"schema":"qwen-public-receipt-verification/v1",
            "state":"PASS_GHA_SOURCE_AND_JOB_STATUS",
            "network_class":"PUBLIC_GITHUB_READ_ONLY",
            "admission_authorized":False,
            "semantic_model_claims_verified":False,
            "packets":len(details),
            "external_job_assertions":sum(x["independent_required_jobs"] for x in details),
            "results":details}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ledger",default=str(HERE.parent/"qwen_batches/workset.public.json"))
    p.add_argument("--expected",default=str(HERE/"reviewed-job-oracles.json"))
    p.add_argument("--output",default=None)
    args=p.parse_args()
    doc=json.loads(Path(args.ledger).read_text())
    expected=json.loads(Path(args.expected).read_text())
    result=verify(doc,expected,live_get)
    raw=json.dumps(result,sort_keys=True,indent=2)+"\n"
    if args.output:
        Path(args.output).write_text(raw)
    print(raw)


if __name__=="__main__":
    main()
