#!/usr/bin/env python3
"""Classify independently repeated, actual installed-Qwen native task receipts.

Scientific collection success != model-task success. Keep every negative sample;
never silently accept unexpected failure as a model competence negative.
No file contents, tokens, hidden nonce, private path or stderr in output.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

EXPECTED={
    "schema":"agent-embodiment-native-use/v1",
    "framework":"QWEN_CODE_0_28_3",
    "runtime":"OLLAMA_0_34_1_QWEN3_1P7B_32K",
    "source_class":"PUBLIC_SYNTHETIC",
    "model_inference":"ACTUAL",
    "operational_admission":"NOT_GRANTED",
}
PASS={"tool_lineage_class":"PASS","final_answer_class":"EXACT_FINAL",
      "independent_hidden_oracle":"PASS","post_run_profile_integrity":"PASS",
      "verdict":"PASS"}
ALLOWED_FINAL={"EXACT_FINAL","EXPECTED_WITH_EXTRA","WRONG_FINAL","INVALID_OR_MISSING_RESULT","DECOY_IN_FINAL","EMPTY_FINAL"}
def fixture_fingerprint(task: Path) -> str:
    """Commit to the three public-synthetic inputs, never their raw contents."""
    entries = {}
    for name in ("index.txt", "a.txt", "b.txt"):
        path = task / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise ValueError("invalid synthetic fixture")
        entries[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def execution_identity(trial: int) -> dict:
    return {"run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "job": os.environ["GITHUB_JOB"],
            "source_sha": os.environ["GITHUB_SHA"], "trial_index": trial}


def verify_evidence(data: dict, trial: int, source: str) -> None:
    identity = data.get("execution")
    if (not isinstance(identity, dict)
            or set(identity) != {"run_id","run_attempt","job","source_sha","trial_index"}
            or identity.get("source_sha") != source):
        raise ValueError("missing or mismatched execution source")
    if type(identity.get("trial_index")) is not int or identity["trial_index"] != trial:
        raise ValueError("missing or mismatched trial identity")
    for key in ("run_id", "run_attempt"):
        value = identity.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
            raise ValueError("invalid execution identity")
    job = identity.get("job")
    if not isinstance(job, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", job):
        raise ValueError("invalid job identity")
    for key in ("fixture_before_sha256", "fixture_after_sha256", "model_stdout_sha256"):
        value = data.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("missing or invalid evidence digest")
    if data["fixture_before_sha256"] != data["fixture_after_sha256"]:
        raise ValueError("synthetic fixture changed during execution")


def classify(data: dict, script_exit: int, trial: int, source: str) -> dict:
    if not isinstance(data,dict):raise ValueError("no classification object")
    if type(trial) is not int or trial<1 or trial>16:raise ValueError("invalid trial index")
    if not isinstance(source,str) or not re.fullmatch(r"[a-f0-9]{40}",source):raise ValueError("invalid source revision")
    if type(script_exit) is not int or script_exit not in (0,1):raise ValueError("unexpected wrapper outcome")
    verify_evidence(data,trial,source)
    for key,val in EXPECTED.items():
        if data.get(key)!=val:raise ValueError("unqualified receipt field: "+key)
    if type(data.get("cli_exit")) is not int or data["cli_exit"]!=0:
        raise ValueError("native Qwen process itself failed; not model-task negative")
    if data.get("post_run_profile_integrity")!="PASS":
        raise ValueError("config or runtime drift; not model-task negative")
    drift=data.get("post_run_settings_drift")
    if not isinstance(drift,dict) or drift.get("class")!="UNCHANGED" or drift.get("byte_identical") is not True:
        raise ValueError("missing post-run settings invariant")
    semantic_success=(data.get("tool_lineage_class")=="PASS" and
                      data.get("final_answer_class")=="EXACT_FINAL" and
                      data.get("independent_hidden_oracle")=="PASS")
    if data.get("verdict")!=("PASS" if semantic_success else "FAIL"):
        raise ValueError("receipt verdict contradicts independent semantic evidence")
    model_success=semantic_success
    if model_success and script_exit!=0:
        raise ValueError("script failed despite task PASS")
    if not model_success and script_exit!=1:
        raise ValueError("script reported success despite task FAIL")
    if data.get("final_answer_class") not in ALLOWED_FINAL:
        raise ValueError("unrecognized final-answer classification")
    if data.get("independent_hidden_oracle") not in ("PASS","FAIL"):
        raise ValueError("unrecognized hidden oracle outcome")
    if data.get("tool_lineage_class") not in ("PASS","INVALID_TARGET","INVALID_JSON",
               "INVALID_FRAME","UNEXPECTED_TOOL","INVALID_ARGS","OUT_OF_SCOPE",
               "MISSING_TOOL_ID","INVALID_RESULT_ID","TOOL_RESULT_ERROR",
               "WRONG_TOOL_COUNT","REUSED_TOOL_ID","WRONG_READ_SEQUENCE",
               "MISSING_OR_MISORDERED_TOOL_RESULT","OVERLAPPING_TOOL_USE",
               "UNMATCHED_TOOL_RESULT","PREMATURE_FINAL_RESULT","NONTERMINAL_FINAL_RESULT",
               "MISSING_FINAL_RESULT","INVALID_MESSAGE","INVALID_CONTENT","INVALID_CONTENT_BLOCK",
               "INVALID_PATH","INVALID_TOOL_USE_FRAME","INVALID_TOOL_RESULT_FRAME"):
        # Report novel classifications as infrastructure/evaluation drift, not a task failure.
        raise ValueError("unrecognized tool-lineage class")
    return {
        "schema":"qwen-r25-independent-trial/v1",
        "source_sha":source,
        "trial_index":trial,
        "embodiment":"PUBLIC_GHA_EPHEMERAL_LINUX_AMD64",
        "treatment":"QWEN_0_28_3_OLLAMA_0_34_1_QWEN3_1P7B_32K_R18_TWOHOP",
        "task_verdict":"TASK_PASS" if model_success else "TASK_FAIL",
        "tool_lineage_class":data["tool_lineage_class"],
        "final_answer_class":data["final_answer_class"],
        "independent_hidden_oracle":data["independent_hidden_oracle"],
        "post_run_profile_integrity":"PASS",
        "model_process_exit":0,
        "model_inference":"ACTUAL",
        "workcell_admission":"NOT_GRANTED",
        "actor_role_qualification":"NOT_GRANTED",
        "fixture":"RANDOMIZED_HIDDEN_INDEX_TARGET_AND_DECOY",
        "execution":data["execution"],
        "fixture_sha256":data["fixture_before_sha256"],
        "model_stdout_sha256":data["model_stdout_sha256"],
        "receipt_evidence_sha256":hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    }

def selftest():
    source="a"*40
    good={**EXPECTED,**PASS,
        "cli_exit":0,
        "execution":{"run_id":"1","run_attempt":"1","job":"fixture","source_sha":source,"trial_index":1},
        "fixture_before_sha256":"b"*64,"fixture_after_sha256":"b"*64,"model_stdout_sha256":"c"*64,
        "post_run_settings_drift":{"class":"UNCHANGED","byte_identical":True}}
    assert classify(good,0,1,source)["task_verdict"]=="TASK_PASS"
    bad=dict(good,verdict="FAIL",tool_lineage_class="WRONG_TOOL_COUNT",
             final_answer_class="WRONG_FINAL",independent_hidden_oracle="FAIL")
    bad["execution"]=dict(good["execution"],trial_index=2)
    assert classify(bad,1,2,source)["task_verdict"]=="TASK_FAIL"
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as d:
        task=Path(d)
        for name in ("index.txt","a.txt","b.txt"):(task/name).write_text(name)
        first=fixture_fingerprint(task)
        assert fixture_fingerprint(task)==first
        (task/"a.txt").write_text("changed")
        second=fixture_fingerprint(task)
        assert first!=second
    distinct=dict(good,execution=dict(good["execution"],trial_index=2),
                  fixture_before_sha256=second,fixture_after_sha256=second,model_stdout_sha256="d"*64)
    assert classify(good,0,1,source)["receipt_evidence_sha256"]!=classify(distinct,0,2,source)["receipt_evidence_sha256"]
    for label in ("INVALID_PATH","PREMATURE_FINAL_RESULT","INVALID_TOOL_USE_FRAME"):
        observed=dict(good,verdict="FAIL",tool_lineage_class=label)
        assert classify(observed,1,1,source)["task_verdict"]=="TASK_FAIL"
    mutations=[
        (dict(good,cli_exit=1),0),
        (dict(good,model_inference="SIMULATED"),0),
        (dict(good,post_run_profile_integrity="FAIL"),0),
        (dict(good,tool_lineage_class="UNKNOWN"),0),
        (dict(bad,verdict="PASS"),1),
        (good,1),(bad,0),
        (dict(good,execution=None),0),
        (dict(good,execution=dict(good["execution"],source_sha="b"*40)),0),
        (dict(good,execution=dict(good["execution"],trial_index=True)),0),
        (dict(good,fixture_before_sha256=None),0),
        (dict(good,fixture_after_sha256="d"*64),0),
        (dict(good,model_stdout_sha256="short"),0),
        (dict(good,cli_exit=False),0),
    ]
    for receipt,rc in mutations:
        try:classify(receipt,rc,receipt.get("execution",{}).get("trial_index",1) if isinstance(receipt.get("execution"),dict) else 1,source)
        except ValueError:pass
        else:raise AssertionError("malformed model result classified as qualified")
    print(json.dumps({"schema":"qwen-r25-critic/v1","verdict":"PASS",
        "positive_model_pass":1,"positive_model_fail":1,
        "negative_infra_or_false_receipts":len(mutations)},sort_keys=True))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("self-test","classify"))
    p.add_argument("--receipt",type=Path)
    p.add_argument("--output",type=Path)
    p.add_argument("--script-exit",type=int)
    p.add_argument("--trial",type=int)
    p.add_argument("--source-sha")
    args=p.parse_args()
    if args.action=="self-test":selftest();return
    if args.receipt is None or args.output is None or args.script_exit is None or args.trial is None or args.source_sha is None:
        p.error("classify requires --receipt --output --script-exit --trial --source-sha")
    data=json.loads(args.receipt.read_text(encoding="utf-8"))
    record=classify(data,args.script_exit,args.trial,args.source_sha)
    if record["execution"] != execution_identity(args.trial):
        raise ValueError("receipt execution does not match current runner")
    args.output.write_text(json.dumps(record,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(record,sort_keys=True))
if __name__=="__main__":main()
