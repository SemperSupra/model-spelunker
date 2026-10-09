#!/usr/bin/env python3
"""Allowlisted, idempotent DLE return for synthetic free-model interviews."""
import argparse
import json
from pathlib import Path
import re
import subprocess

REPO="SemperSupra/model-spelunker"
ISSUE=139
TASK="boundary-bugfix-v0"
ARTIFACT="ghcr.io/sempersupra/model-spelunker-harness-openworker@sha256:e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83"
MODELS=(
    "cohere/north-mini-code:free",
    "poolside/laguna-s-2.1:free",
)
SHA=re.compile(r"sha256:[a-f0-9]{64}")
COMMIT=re.compile(r"[a-f0-9]{40}")

def reduce_receipt(data):
    if not isinstance(data,dict):
        raise ValueError("not an object")
    candidate=data.get("candidate") or {}
    model=candidate.get("model") or {}
    model_id=model.get("id")
    if model_id not in MODELS or model.get("provider")!="openrouter":
        raise ValueError("wrong provider/model")
    if (candidate.get("harness") or {}).get("artifact_ref")!=ARTIFACT:
        raise ValueError("wrong immutable harness artifact")
    if (data.get("task") or {}).get("id")!=TASK:
        raise ValueError("wrong task")
    digest=data.get("evidence_digest")
    if not isinstance(digest,str) or not SHA.fullmatch(digest):
        raise ValueError("invalid evidence digest")
    obs=data.get("observation") or {}
    good=obs.get("success")
    rc=obs.get("verifier_exit_code")
    tools=obs.get("tool_calls")
    if type(good)!=bool or type(rc)!=int or type(tools)!=int or tools<0:
        raise ValueError("invalid result")
    if (good and rc!=0) or (not good and rc==0):
        raise ValueError("verifier/result disagreement")
    counts=(obs.get("workload") or {}).get("provider_finish_reason_counts") or {}
    if not isinstance(counts,dict):
        raise ValueError("invalid finish reasons")
    safe={}
    for reason in ("stop","tool_calls","length","content_filter"):
        value=counts.get(reason,0)
        if type(value)!=int or value<0:
            raise ValueError("invalid count")
        if value:
            safe[reason]=value
    classification=obs.get("failure_class")
    if classification not in ("false-completion","tool-protocol","timeout","candidate-error","task-state"):
        classification="other-or-none"

    # A deterministic verifier can legitimately reject an unchanged task
    # after a provider rejected the model request. That is NOT evidence that
    # the model tried and failed the semantic task. Separate the failure
    # plane before emitting any task-class support/negative evidence.
    errors=obs.get("engine_error_types") or []
    if not isinstance(errors,list):
        raise ValueError("invalid engine error evidence")
    observed_error_types=sorted({
        e for e in errors if isinstance(e,str)
        and e in ("RateLimitError","ProviderError","APIConnectionError","APITimeoutError")
    })
    signals=obs.get("failure_signals") or []
    if not isinstance(signals,list):
        raise ValueError("invalid failure signals")
    workload=obs.get("workload") or {}
    rounds=workload.get("model_rounds",0)
    if type(rounds)!=int or rounds<0:
        raise ValueError("invalid model round count")
    if good:
        state="PASS"
    elif "RateLimitError" in observed_error_types:
        state="PROVIDER_RATE_LIMIT_CENSORED"
    elif "engine-error-event" in signals or observed_error_types:
        state="PROVIDER_OR_ENGINE_CENSORED"
    elif obs.get("timed_out") is True:
        state="TIMEOUT_CENSORED"
    elif rounds==0:
        state="NO_MODEL_COMPLETION_CENSORED"
    else:
        state="SEMANTIC_FAIL"
    raw_names=workload.get("tool_name_counts")
    safe_names={}
    if raw_names is not None:
        if not isinstance(raw_names,dict):
            raise ValueError("invalid tool name counts")
        if set(raw_names)-{"list_files","read_file","write_file"}:
            raise ValueError("unknown tool in admitted task projection")
        for name,value in raw_names.items():
            if type(value)!=int or value<0:
                raise ValueError("invalid tool count")
            safe_names[name]=value
    approvals={}
    for name in ("write_approvals_granted","write_approvals_denied"):
        value=workload.get(name)
        if value is not None:
            if type(value)!=int or value<0:
                raise ValueError("invalid write approval count")
            approvals[name]=value
    return {
        "model_id":model_id,
        "state":state,
        "observed_tool_name_counts":safe_names,
        **approvals,
        "evidence_digest":digest,
        "external_verifier_exit_code":rc,
        "tool_calls":tools,
        "provider_finish_reason_counts":safe,
        "observed_engine_error_types":observed_error_types,
        "completed_model_rounds":rounds,
        "candidate_exited_zero":obs.get("candidate_exit_code")==0,
        "failure_class":classification,
    }

def reduce_folder(folder,run,commit,expected_models=MODELS):
    if run<=0 or not COMMIT.fullmatch(commit):
        raise ValueError("bad workflow provenance")
    if (not expected_models or len(set(expected_models))!=len(expected_models)
            or any(model not in MODELS for model in expected_models)):
        raise ValueError("unknown or duplicate experiment model")
    rows={m:{"model_id":m,"state":"NO_RECEIPT"} for m in expected_models}
    for path in sorted(folder.rglob("*.json")) if folder.exists() else []:
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            row=reduce_receipt(data)
        except (ValueError,KeyError,TypeError):
            continue
        model=row["model_id"]
        if model not in rows:
            raise ValueError("receipt from unselected model")
        if rows[model]["state"]!="NO_RECEIPT":
            raise ValueError("duplicate model receipt")
        rows[model]=row
    return {
        "schema_version":1,
        "record_type":"openworker-free-model-interview-result",
        "source_run":run,
        "source_commit":commit,
        "run_url":f"https://github.com/{REPO}/actions/runs/{run}",
        "harness_artifact":ARTIFACT,
        "task":TASK,
        "interpretation":"single-rep-verifier-evidence-no-general-support-claim",
        "treatments":[rows[m] for m in expected_models],
    }

def body_of(result):
    marker="<!-- openworker-free-model-interview:v1:"+str(result["source_run"])+" -->"
    fence=chr(96)*3
    return (marker+"\n### Stronger free-model OpenWorker workcell receipts\n\n"
            +"NO_RECEIPT and provider/timeout CENSORED states are not semantic model "
            +"task failures. Only an observed completed task with an external "
            +"verifier failure is SEMANTIC_FAIL.\n\n"
            +fence+"json\n"+json.dumps(result,sort_keys=True,indent=2)
            +"\n"+fence+"\n")

def gh_api(args):
    p=subprocess.run(["gh","api",*args],capture_output=True,text=True)
    if p.returncode!=0:
        raise RuntimeError("GitHub DLE API unavailable")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("malformed GitHub API response") from exc

def post_once(body):
    endpoint=f"repos/{REPO}/issues/{ISSUE}/comments"
    pages=gh_api(["--paginate","--slurp",endpoint+"?per_page=100"])
    if not isinstance(pages,list):
        raise RuntimeError("invalid DLE comment listing")
    all_comments=[c for page in pages for c in (page if isinstance(page,list) else [page])]
    marker=body.splitlines()[0]
    matches=[c for c in all_comments if isinstance(c,dict) and marker in str(c.get("body",""))]
    if matches:
        if any(c.get("body")!=body for c in matches):
            raise ValueError("DLE run key conflicts with existing evidence")
        return {"state":"ALREADY_RECORDED","comment_url":matches[0].get("html_url")}
    added=gh_api(["--method","POST",endpoint,"-f","body="+body])
    if not isinstance(added,dict) or added.get("body")!=body or not added.get("html_url"):
        raise RuntimeError("DLE receipt not acknowledged")
    return {"state":"RECORDED","comment_url":added["html_url"]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--receipts-dir",required=True,type=Path)
    parser.add_argument("--run-id",required=True,type=int)
    parser.add_argument("--commit",required=True)
    parser.add_argument("--expected-model",action="append",choices=MODELS)
    a=parser.parse_args()
    models=tuple(a.expected_model) if a.expected_model else MODELS
    result=reduce_folder(a.receipts_dir,a.run_id,a.commit,models)
    answer=post_once(body_of(result))
    print(json.dumps({"dle":answer,"run_id":a.run_id,
       "results":[{"model_id":r["model_id"],"state":r["state"]} for r in result["treatments"]]},
       sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
