#!/usr/bin/env python3
"""R3 independent native-model recovery from actually committed R0 evictions.

Consumes source-verified Go checkpoint + eviction receipts; performs bounded,
same-model post-interruption evidence selection using memory reconstruction.
No tool execution or autonomous memory promotion, no physical KV cache proof.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hmrc_native_memory_r2 as memory

QUESTIONS=("next_step","german","thai")
ARMS=("no-recall","source-scoped-fts")

def input_receipt(state:dict,policy:dict,fixture:dict)->None:
    if policy.get("schema")!="hmrc-r3-native-joined-public" or \
       not policy.get("native_model_telemetry") or \
       policy.get("runtime_context_tokens",0)<policy.get("policy_context_cap_synthetic",0) or \
       not policy.get("recovery_verified") or not policy.get("protected_survived") or \
       policy.get("full_agent_task_qualified") or policy.get("physical_kv_cache_qualified"):
        raise ValueError("unqualified native policy/telemetry receipt")
    if state.get("Generation")!=policy["after_generation"] or \
       state.get("Schema")!="hmrc-r0" or state.get("Scope")!="atlas":
        raise ValueError("checkpoint generation or scope does not match receipt")
    protected=[x for x in state["Units"] if x.get("ID")=="protected"]
    if len(protected)!=1 or protected[0]["SourceID"]!="SYN_ATLAS_DLE_R8_HOLD":
        raise ValueError("protected authority missing after compaction")
    evicted=state.get("Evicted",[])
    if len(evicted)!=2 or \
       [x["SourceID"] for x in evicted]!=policy["evicted_source_ids"] or \
       [x["SourceDigest"] for x in evicted]!=policy["evicted_source_sha256"]:
        raise ValueError("eviction receipt mismatched state")
    corpus={d["id"]:d for d in fixture["corpus"]}
    for e in evicted:
        d=corpus[e["SourceID"]]
        if d["project"]!="atlas" or d["authority"] not in ("accepted","advisory"):
            raise ValueError("source lost scope or authority")
        dig="sha256:"+hashlib.sha256(d["text"].encode()).hexdigest()
        if e["SourceDigest"]!=dig:
            raise ValueError("independently recomputed evicted content digest mismatch")
    q={x["id"]:x for x in fixture["questions"]}
    if not all(q[k]["expect"] in policy["evicted_source_ids"] for k in QUESTIONS):
        raise ValueError("selected task does not need evicted context")

def run(state_path:Path,policy_path:Path,out:Path):
    fixture,sha=memory.load_fixture()
    state=json.loads(state_path.read_text())
    policy=json.loads(policy_path.read_text())
    input_receipt(state,policy,fixture)
    db,byid=memory.build_corpus(fixture,100,11)
    questions={q["id"]:q for q in fixture["questions"]}
    rows=[]
    try:
        for question_id in QUESTIONS:
            q=questions[question_id]
            for arm in ARMS:
                docs=memory.context_units(db,byid,q["query"],arm)
                text=memory.prompt_for(q["query"],docs)
                body={
                    "model":"qwen3:1.7b","prompt":text,"stream":False,
                    "format":"json","think":False,"keep_alive":"5m",
                    "options":{"temperature":0,"num_predict":96,"num_ctx":32768},
                }
                started=time.monotonic()
                response=memory.api("http://127.0.0.1:11434/api/generate",body)
                elapsed=round(time.monotonic()-started,3)
                if response.get("model")!="qwen3:1.7b" or response.get("done") is not True:
                    raise ValueError("unexpected model or incomplete generation")
                answer=memory.decode_source(str(response.get("response","")))
                rows.append({
                    "question":question_id,"arm":arm,
                    "expected":q["expect"],"observed":answer,
                    "correct":answer==q["expect"],
                    "retrieval_found_evicted_source":q["expect"] in [d["id"] for d in docs],
                    "candidate_ids":[d["id"] for d in docs],
                    "wall_seconds":elapsed,
                    "prompt_eval_count":response.get("prompt_eval_count"),
                    "eval_count":response.get("eval_count"),
                    "response_sha256":hashlib.sha256(str(response.get("response","")).encode()).hexdigest(),
                })
    finally:
        db.close()
    if len(rows)!=len(QUESTIONS)*len(ARMS):
        raise ValueError("incomplete model-backed recovery")
    summary={arm:sum(x["correct"] for x in rows if x["arm"]==arm) for arm in ARMS}
    receipt={
        "schema":"hmrc-r3-native-model-recovered-evidence-v1",
        "fixture_sha256":sha,"checkpoint_generation":state["Generation"],
        "policy_synthetic_cap":policy["policy_context_cap_synthetic"],
        "runtime_context_reported":policy["runtime_context_tokens"],
        "evicted_source_ids":policy["evicted_source_ids"],
        "real_native_model_inference_executed":True,
        "full_agent_task_qualified":False,"physical_kv_cache_qualified":False,
        "memory_granted_authority":False,
        "retrieval_method":"existing externally source-scoped SQLite FTS5",
        "control":"same-model no-recall",
        "limits":["selected three positive queries", "single model/seed",
                  "synthetic effective context budget", "no actual full harness tool transactions",
                  "no negative-abstention or cross-tenant proof in this microintegration"],
        "summary":summary,"rows":rows,
    }
    out.write_text(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print("NATIVE_MODEL_EVICTED_CONTEXT_RECOVERY="+json.dumps(summary,sort_keys=True))
    print("AUTONOMOUS_COMPACTION=NOT_ADMITTED; KV_CACHE=UNMEASURED; AGENT_TASK=NOT_RUN")

def self_test():
    fixture,sha=memory.load_fixture()
    assert len(sha)==64 and len(fixture["corpus"])==8
    q={x["id"]:x for x in fixture["questions"]}
    expected={q[k]["expect"] for k in QUESTIONS}
    assert expected=={"SYN_ATLAS_DLE_R8_NEXT","SYN_ATLAS_CPE_R5_BLUE"}
    assert all(k in q for k in QUESTIONS)
    print("PASS independent selected-source goal and synthetic oracle; model NOT_RUN")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--state",type=Path)
    p.add_argument("--policy",type=Path)
    p.add_argument("--out",type=Path)
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.state or not a.policy or not a.out:p.error("state, policy and out required")
        run(a.state,a.policy,a.out)
