#!/usr/bin/env python3
"""#306 R4 native OpenViking hot/cold lifecycle primitive, providerless.

Fetches exact upstream AGPL source at commit+blob SHA, runs actual native
hotness_score() with only the Python standard library. Contrasts a naive
hotness-driven eviction policy to source/authority-aware selection. This is
NOT full OpenViking L0/L1/L2 retrieval, session ingestion or model/embedding
qualification. No upstream source is redistributed in this project.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import urllib.request

UPSTREAM_COMMIT="aa885b902075e17b13756266049de3c21ac4ae43"
UPSTREAM_PATH="openviking/retrieve/memory_lifecycle.py"
UPSTREAM_BLOB="003a4c1b7e000af8d766ae5f9e4f4fcc1b28fcc7"
NOW=datetime(2026,2,26,12,0,0,tzinfo=timezone.utc)

def blob_sha(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def load_native(dest:Path):
    url=f"https://raw.githubusercontent.com/volcengine/OpenViking/{UPSTREAM_COMMIT}/{UPSTREAM_PATH}"
    req=urllib.request.Request(url,headers={"User-Agent":"hmrc-openviking-native-r4"})
    with urllib.request.urlopen(req,timeout=35) as res:
        raw=res.read(4097)
        if res.status!=200:raise ValueError("upstream not available")
    if len(raw)>4096 or blob_sha(raw)!=UPSTREAM_BLOB:
        raise ValueError("upstream source change/downgrade/oversize")
    dest.write_bytes(raw)
    spec=importlib.util.spec_from_file_location("ov_native_lifecycle",dest)
    if spec is None or spec.loader is None:raise ValueError("module load denied")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod,hashlib.sha256(raw).hexdigest()

@dataclass(frozen=True)
class Memory:
    id:str
    scope:str
    kind:str
    verified:bool
    active_count:int
    age_days:int

def data(seed):
    rng=random.Random(seed)
    result=[]
    # Under hotness-only policy, old protected state will look cold, while
    # recent untrusted advisory content will look warm.
    for i in range(10):
        result.append(Memory(f"owner-{i}","atlas","protected",True,0,100+i))
    for i in range(10):
        result.append(Memory(f"active-{i}","atlas","active",True,0,90+i))
    for i in range(50):
        result.append(Memory(f"history-{i}","atlas","historical",True,rng.randint(0,4),rng.randint(20,60)))
    for i in range(10):
        result.append(Memory(f"advisory-{i}","atlas","historical",False,rng.randint(8,20),rng.randint(0,3)))
    for i in range(10):
        result.append(Memory(f"foreign-{i}","vega","historical",True,0,rng.randint(30,60)))
    return result

def score(native,mem):
    return native.hotness_score(mem.active_count,NOW-timedelta(days=mem.age_days),now=NOW)

def choose(native,memories,policy,evict=35):
    if policy=="hotness-only":
        pool=list(memories)
    elif policy=="source-first":
        pool=[x for x in memories if x.kind=="historical" and x.verified and x.scope=="atlas"]
    else:raise ValueError("unknown lifecycle treatment")
    if len(pool)<evict:raise ValueError("safe storage pressure: cannot evict protected records")
    selected=sorted(pool,key=lambda r:(score(native,r),r.id))[:evict]
    return selected

def run(out,policy):
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="hmrc-viking-source-r4-") as d:
        native,sha=load_native(Path(d)/"memory_lifecycle.py")
        assert abs(native.hotness_score(0,NOW,now=NOW)-0.5)<1e-10
        assert native.hotness_score(200,None,now=NOW)==0.
        assert native.hotness_score(100,NOW,now=NOW)>native.hotness_score(1,NOW,now=NOW)
        assert native.hotness_score(1,NOW,now=NOW)>native.hotness_score(1,NOW-timedelta(days=7),now=NOW)
        records=[]
        for seed in (11,29,47):
            memory=data(seed)
            selected=choose(native,memory,policy)
            receipts={
                "seed":seed,"evicted":len(selected),
                "protected_evict":sum(x.kind=="protected" for x in selected),
                "active_evict":sum(x.kind=="active" for x in selected),
                "foreign_evict":sum(x.scope!="atlas" for x in selected),
                "unverified_evict":sum(not x.verified for x in selected),
                "exact_evicted_ids":[x.id for x in selected],
                "score_min":min(score(native,x) for x in selected),
                "score_max":max(score(native,x) for x in selected),
            }
            if policy=="source-first" and any(receipts[k] for k in (
                "protected_evict","active_evict","foreign_evict","unverified_evict")):
                raise AssertionError("source-first retention invariant violated")
            records.append(receipts)
        evidence={
            "schema":"hmrc-openviking-hotness-r4",
            "upstream":"volcengine/OpenViking","commit":UPSTREAM_COMMIT,
            "native_path":UPSTREAM_PATH,"native_git_blob":UPSTREAM_BLOB,
            "native_sha256":sha,"engine":"actual upstream pure-Python hotness_score",
            "upstream_license":"AGPL-3.0; review before integration",
            "runtime":"Python stdlib, upstream module loaded without installing full platform",
            "policy":policy,"records":records,
            "real_vendor_hotness_executed":True,
            "full_openviking_platform_executed":False,
            "l0_l1_l2_session_retrieval_executed":False,
            "model_or_embeddings_executed":False,
            "authority_source":"synthetic external metadata; not conferred by score",
            "limitations":["native hotness primitive only, not full hierarchical engine",
                           "scores are heuristics; no token/KV savings shown",
                           "source eligibility is an external deterministic guard",
                           "AGPL-3.0 and transitive dependencies not cleared"],
        }
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
        print("NATIVE_UPSTREAM_OPENVIKING_HOTNESS=EXECUTED; FULL_PLATFORM=NOT_RUN")
        print("UPSTREAM_LIFECYCLE_RESULT="+json.dumps({
            "policy":policy,"protected_evict":sum(r["protected_evict"] for r in records),
            "active_evict":sum(r["active_evict"] for r in records),
            "foreign_evict":sum(r["foreign_evict"] for r in records),
            "unverified_evict":sum(r["unverified_evict"] for r in records)},sort_keys=True))

def self_test():
    assert len(data(11))==90
    assert data(11)==data(11)
    assert data(11)!=data(29)
    assert blob_sha(b"hello")=="b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"
    try:choose(None,[],"source-first",evict=1)
    except ValueError:pass
    else:raise AssertionError("safe headroom failure was not rejected")
    try:choose(None,[],"unexpected",evict=0)
    except ValueError:pass
    else:raise AssertionError("unregistered policy accepted")
    print("PASS deterministic synthetic custody and hash screening; upstream native NOT_RUN")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--policy",choices=("hotness-only","source-first"))
    p.add_argument("--out",type=Path)
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if a.out is None or a.policy is None:p.error("--policy and --out required")
        run(a.out,a.policy)
