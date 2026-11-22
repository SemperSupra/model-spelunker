#!/usr/bin/env python3
"""Direct native Engram/ReMe retrieval load interview on public synthetic records.

Not an agent performance test. Strictly source-pinned vendor binaries supplied
by the caller; authoritative decision remains with the external source oracle.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import tempfile
import time

BASE = Path(__file__).with_name("memory_hierarchy_cpu_bakeoff.py")
spec = importlib.util.spec_from_file_location("memory_hierarchy_cpu_bakeoff", BASE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

PHRASES = (
    "signed release admission verifier decision",
    "blue-signal German blaues Signal concept mapping",
    "Thai สัญญาณสีน้ำเงิน canonical lexical identity",
    "next executable pinned source digest",
    "Observe Plan Apply Verify operational practice",
    "rejected old historical release approved",
)

def augment(data, count, seed):
    # Same-project plausible distractors, deliberately source-nonauthoritative.
    # These exercise retrieval relevance, not project-isolation efficacy.
    fixture = json.loads(json.dumps(data))
    rng = random.Random(seed)
    for n in range(count):
        phrase = PHRASES[rng.randrange(len(PHRASES))]
        fixture["corpus"].append({
            "id": f"SYN_ATLAS_LOAD_{seed}_{n:05d}",
            "project": "atlas",
            "domain": "STRESS",
            "revision": 0,
            "authority": "advisory",
            "text": f"Archived synthetic irrelevant training memo {n}: {phrase}. "
                    "This is not a source for Atlas release, identity or execution.",
        })
    return fixture

def run(provider, decoys, seed):
    fixture, digest = module.load_fixture(), hashlib.sha256(module.FIXTURE.read_bytes()).hexdigest()
    expanded = augment(fixture, decoys, seed)
    expected = {q["id"]:q["expect"] for q in fixture["questions"]}
    with tempfile.TemporaryDirectory(prefix="native-memory-interview-") as tmp:
        start=time.monotonic()
        if provider=="engram":
            results,meta=module.engram(expanded,Path(tmp))
        elif provider=="reme":
            results,meta=module.reme(expanded,Path(tmp))
        else:
            raise ValueError("unknown provider")
        duration=round(time.monotonic()-start,3)
    assert len(results)==8 and meta["native_write_count"]>=decoys
    positives=[row for row in results if expected[row["id"]] is not None]
    negatives=[row for row in results if expected[row["id"]] is None]
    return {
        "schema":"native-memory-load-interview-v1",
        "provider":provider,"decoys":decoys,"seed":seed,
        "original_fixture_sha256":digest,
        "synthetic_only":True,
        "source_authority_unchanged":True,
        "model_inference_executed":False,
        "agent_task_accepted":False,
        "memory_lift_qualified":False,
        "native_provider_executed":True,
        "source_commit":os.environ.get("BAKEOFF_SOURCE_SHA","unknown"),
        "positives":len(positives),
        "recall_at_3":sum(r["expected_source_recalled"] for r in positives),
        "top1":sum(r["expected_source_top1"] for r in positives),
        "stale_exposure_queries":sum(r["superseded_source_seen"] for r in results),
        "negative_nonabstention":sum(r["no_evidence_non_abstention"] for r in negatives),
        "foreign_exposures":sum(r["cross_project_source_seen"] for r in results),
        "returned_bytes":sum(r["returned_bytes"] for r in results),
        "elapsed_seconds":duration,
        "meta":meta,
        "results":[{"query":r["id"],
                    "source_ids_seen":r["source_ids_seen"],
                    "recalled":r["expected_source_recalled"],
                    "top1":r["expected_source_top1"],
                    "stale":r["superseded_source_seen"],
                    "foreign":r["cross_project_source_seen"],
                    "ms":r["observed_ms"]} for r in results],
        "limits":["native backend, original public synthetic corpus and original queries",
                  "not equal setup cost across Go CLI and HTTP ReMe",
                  "one seed, no LLM, no agent success claim",
                  "project Atlas decoys, not separate-tenant boundary test",
                  "ReMe may index asynchronously; use actual observed receipts"],
    }

def self_test():
    data=module.load_fixture()
    a=augment(data,100,11)
    assert len(a["corpus"])==108 and len(data["corpus"])==8
    assert a==augment(data,100,11)
    assert a!=augment(data,100,29)
    ids=[x["id"] for x in a["corpus"]]
    assert len(set(ids))==108
    assert all(x["project"]=="atlas" and x["authority"]=="advisory"
               for x in a["corpus"][8:])
    print("PASS deterministic public stress corpus and immutable original fixture")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--provider",choices=("engram","reme"))
    p.add_argument("--decoys",type=int,choices=(100,1000))
    p.add_argument("--seed",type=int,default=11)
    p.add_argument("--out",type=Path)
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test: self_test(); return
    if a.provider is None or a.decoys is None or a.out is None:
        p.error("provider, decoys, and out required")
    receipt=run(a.provider,a.decoys,a.seed)
    a.out.write_text(json.dumps(receipt,sort_keys=True,indent=2,ensure_ascii=False)+"\n")
    print(f"NATIVE_MEMORY_INTERVIEW {a.provider} {a.decoys} recall={receipt['recall_at_3']}/6 "
          f"stale={receipt['stale_exposure_queries']} false_negative={receipt['negative_nonabstention']} "
          "NO_AGENT_MODEL_LIFT")
if __name__=="__main__": main()
