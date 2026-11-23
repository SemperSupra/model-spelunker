#!/usr/bin/env python3
"""R8 #306 independently frozen paraphrase/no-evidence evaluation.

Reuses EXACT R7 public Qwen model endpoint, ontology and Go canonical
source verifier, without modifying their implementations, aliases or task.
R8 is a novel *question set*; there is no training/fitting. All memory
source and authority remain synthetic advisory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import hmrc_nl_extract_r7 as r7

FIX=Path(__file__).with_name("fixtures")/"hmrc_r8_semantic_paraphrases.json"

def load():
    original,original_sha=r7.read()
    raw=FIX.read_bytes()
    fixture=json.loads(raw)
    assert fixture["schema"]=="hmrc-r8-ood-paraphrase-v1" and fixture["public_synthetic_only"]
    assert len(fixture["questions"])==28
    assert len([x for x in fixture["questions"] if x["expected_state"]=="SUPPORTED"])==12
    assert len([x for x in fixture["questions"] if x["expected_state"]=="ABSTAIN"])==16
    assert set(x["language"] for x in fixture["questions"])=={"en","de","th"}
    assert len(set(x["id"] for x in fixture["questions"]))==28
    old={x["question"] for x in original["queries"]}
    assert not any(x["question"] in old for x in fixture["questions"])
    return original,fixture,original_sha,hashlib.sha256(raw).hexdigest()

def predict(model,grammar,original,binary):
    direct=r7.state_for(r7.go_verify(binary,model,original))
    guarded=direct if model==grammar else "ABSTAIN"
    gram=r7.state_for(r7.go_verify(binary,grammar,original))
    return direct,guarded,gram

def self_test():
    ontology,fixture,_,_=load()
    # The original closed-lexicon baseline is intentionally NOT tuned for
    # paraphrases. A failure here is evidence of distribution shift, not bug.
    baseline=[r7.deterministic(ontology,q["question"]) for q in fixture["questions"]]
    assert len(baseline)==28
    assert sum(x==r7.NONE for x in baseline)>=12
    for q in fixture["questions"]:
        p=r7.model_prompt(ontology,q["question"],19,0)
        assert q["id"] not in p
        assert "expected_state" not in p and "expected_subject" not in p
        assert not any(f["value"] in p for f in ontology["facts"])
        assert q["expected_state"] in ("SUPPORTED","ABSTAIN")
    assert r7.parse_model('{"subject":"station-alpha","predicate":"inspection-state","tool_call":"execute"}')==r7.NONE
    print("PASS frozen R8 novel paraphrases, oracle-not-in-prompt, original immutable R7 ontology and baseline shift. MODEL_NOT_RUN")

def run(out:Path,binary:Path,seed:int):
    if seed not in (19,53):raise ValueError("seed not registered")
    ontology,fixture,ontology_sha,fixture_sha=load()
    rows=[]
    start=time.monotonic()
    for i,q in enumerate(fixture["questions"]):
        prompt=r7.model_prompt(ontology,q["question"],seed,i)
        started=time.monotonic()
        model,meta=r7.model_generate(prompt)
        grammar=r7.deterministic(ontology,q["question"])
        raw,guarded,gram=predict(model,grammar,ontology,binary)
        expected=q["expected_state"]
        pair={"subject":q["expected_subject"],"predicate":q["expected_predicate"]} if q["expected_subject"] else r7.NONE
        rows.append({
            "id":q["id"],"language":q["language"],"kind":q["kind"],"expected_state":expected,
            "model_pair":model,"grammar_pair":grammar,
            "model_pair_exact":model==pair,"grammar_pair_exact":grammar==pair,
            "model_source_state":raw,"model_source_correct":raw==expected,
            "model_agreed_source_state":guarded,"model_agreed_source_correct":guarded==expected,
            "grammar_source_state":gram,"grammar_source_correct":gram==expected,
            "model_eval_tokens":meta.get("eval_count"),"prompt_eval_tokens":meta.get("prompt_eval_count"),
            "output_sha256":hashlib.sha256(str(meta.get("response","")).encode()).hexdigest(),
            "seconds":round(time.monotonic()-started,3)
        })
    def score(key):
        return {"total":sum(row[key] for row in rows),
                "positives":sum(row[key] for row in rows if row["expected_state"]=="SUPPORTED"),
                "negatives":sum(row[key] for row in rows if row["expected_state"]=="ABSTAIN")}
    result={
        "schema":"hmrc-r8-real-model-ood-paraphrase",
        "seed":seed,"model":"qwen3:1.7b","native_qwen_inference":True,
        "actual_go_source_verifier":True,"model_calls":28,
        "r7_original_ontology_sha256":ontology_sha,"r8_fixture_sha256":fixture_sha,
        "public_synthetic_only":True,"production_catalog_authenticated":False,
        "model_can_execute_tools":False,"immutable_r7_ontology":True,
        "model_intent_exact":sum(x["model_pair_exact"] for x in rows),
        "grammar_intent_exact":sum(x["grammar_pair_exact"] for x in rows),
        "model_plus_go":score("model_source_correct"),
        "model_plus_go_plus_grammar":score("model_agreed_source_correct"),
        "grammar_plus_go":score("grammar_source_correct"),
        "elapsed_seconds":round(time.monotonic()-start,3),
        "total_prompt_eval_tokens":sum(x["prompt_eval_tokens"] or 0 for x in rows),
        "limitations":["new manually authored paraphrases, not general NLP or hostile human evaluation",
                       "same questions across two shuffled ontology-order seeds",
                       "model sees public original ontology aliases, no source values or labels",
                       "no retrained lexicon, no internet, no persistent memory backend",
                       "source scope is checked-in synthetic, NOT a live authenticated DLE",
                       "no external side effects, tool invocation or context compaction"],
        "rows":rows,
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+"\n")
    print("R8_REAL_QWEN_PARAPHRASE="+json.dumps({
        "seed":seed,"model_intent":result["model_intent_exact"],
        "grammar_intent":result["grammar_intent_exact"],
        "model_go":result["model_plus_go"],
        "model_go_grammar":result["model_plus_go_plus_grammar"],
        "grammar_go":result["grammar_plus_go"]},sort_keys=True))
    print("REAL_QWEN_28_CALLS=YES; R8_NO_PRODUCTION_AUTHORITY")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--out",type=Path)
    p.add_argument("--admit",type=Path)
    p.add_argument("--seed",type=int,default=19)
    args=p.parse_args()
    if args.self_test:self_test()
    else:
        if not args.out or not args.admit:p.error("--out and --admit required")
        run(args.out,args.admit,args.seed)
