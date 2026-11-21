#!/usr/bin/env python3
"""Classify independently repeated, actual installed-Qwen native task receipts.

Scientific collection success != model-task success. Keep every negative sample;
never silently accept unexpected failure as a model competence negative.
No file contents, tokens, hidden nonce, private path or stderr in output.
"""
import argparse
import hashlib
import json
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
def classify(data: dict, script_exit: int, trial: int, source: str) -> dict:
    if not isinstance(data,dict):raise ValueError("no classification object")
    if not isinstance(trial,int) or trial<1 or trial>16:raise ValueError("invalid trial index")
    if not re.fullmatch(r"[a-f0-9]{40}",source):raise ValueError("invalid source revision")
    if script_exit not in (0,1):raise ValueError("unexpected wrapper outcome")
    for key,val in EXPECTED.items():
        if data.get(key)!=val:raise ValueError("unqualified receipt field: "+key)
    if data.get("cli_exit")!=0:
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
               "MISSING_OR_MISORDERED_TOOL_RESULT"):
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
        "receipt_evidence_sha256":hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    }

def selftest():
    source="a"*40
    good={**EXPECTED,**PASS,
        "cli_exit":0,
        "post_run_settings_drift":{"class":"UNCHANGED","byte_identical":True}}
    assert classify(good,0,1,source)["task_verdict"]=="TASK_PASS"
    bad=dict(good,verdict="FAIL",tool_lineage_class="WRONG_TOOL_COUNT",
             final_answer_class="WRONG_FINAL",independent_hidden_oracle="FAIL")
    assert classify(bad,1,2,source)["task_verdict"]=="TASK_FAIL"
    mutations=[
        (dict(good,cli_exit=1),0),
        (dict(good,model_inference="SIMULATED"),0),
        (dict(good,post_run_profile_integrity="FAIL"),0),
        (dict(good,tool_lineage_class="UNKNOWN"),0),
        (dict(bad,verdict="PASS"),1),
        (good,1),(bad,0)
    ]
    for receipt,rc in mutations:
        try:classify(receipt,rc,3,source)
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
    record=classify(json.loads(args.receipt.read_text(encoding="utf-8")),
                    args.script_exit,args.trial,args.source_sha)
    args.output.write_text(json.dumps(record,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(record,sort_keys=True))
if __name__=="__main__":main()
