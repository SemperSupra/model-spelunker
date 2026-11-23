#!/usr/bin/env python3
"""#306 R5: source-pinned upstream OpenViking L0/L1/L2 enum contract PLUS
our independent deterministic scoped promotion oracle.

This is NOT actual OpenViking end-to-end server, storage or retrieval.
It checks exact upstream ContextLevel class from immutable code, then tests a
substitutable owner-side memory pager over public source-backed synthetic
records with bounded bytes and provenance. No vendor runtime service, LLM
embedding, GPU/KV cache, credentials or private records are used.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from enum import Enum
from pathlib import Path
import re
import sqlite3
import urllib.request

UPSTREAM_COMMIT="aa885b902075e17b13756266049de3c21ac4ae43"
UPSTREAM_FILE="openviking/core/context.py"
UPSTREAM_GIT_BLOB="b20d8f5751bdf200bfc093130570d3313f441cd2"
SOURCE=Path(__file__).with_name("fixtures")/"memory_dle_cpe_synthetic_v1.json"
TOKEN_COST_LABEL="UTF8 bytes (not tokenizer tokens)"
MAX_BUDGET=800

def git_blob(content:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(content)).encode()+b"\0"+content).hexdigest()

def load_upstream_levels() -> tuple[type,str]:
    url=f"https://raw.githubusercontent.com/volcengine/OpenViking/{UPSTREAM_COMMIT}/{UPSTREAM_FILE}"
    req=urllib.request.Request(url,headers={"User-Agent":"hmrc-r5-native-level-contract"})
    with urllib.request.urlopen(req,timeout=30) as r:
        raw=r.read(100_001)
        if r.status!=200:raise ValueError("native upstream fetch failed")
    if len(raw)>100_000 or git_blob(raw)!=UPSTREAM_GIT_BLOB:
        raise ValueError("source drift/oversize: reject upstream contract")
    root=ast.parse(raw,filename=UPSTREAM_FILE)
    matches=[n for n in root.body if isinstance(n,ast.ClassDef) and n.name=="ContextLevel"]
    if len(matches)!=1:raise ValueError("no unique upstream hierarchy class")
    node=matches[0]
    if len(node.bases)!=2 or not isinstance(node.bases[0],ast.Name) or node.bases[0].id!="int" or \
       not isinstance(node.bases[1],ast.Name) or node.bases[1].id!="Enum":
        raise ValueError("hierarchy class type drift")
    for n in node.body:
        if not (isinstance(n,(ast.Assign,ast.Expr))):
            raise ValueError("unexpected executable upstream enum members")
    namespace={"Enum":Enum}
    module=ast.Module(body=[node],type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module,UPSTREAM_FILE,"exec"),{"__builtins__":{"int":int},"Enum":Enum},namespace)
    cls=namespace["ContextLevel"]
    got={x.name:x.value for x in cls}
    if got!={"ABSTRACT":0,"OVERVIEW":1,"DETAIL":2}:
        raise ValueError("upstream L0/L1/L2 drift")
    return cls,hashlib.sha256(raw).hexdigest()

def read_fixture():
    raw=SOURCE.read_bytes();d=json.loads(raw)
    if d["schema"]!="synthetic-dle-cpe-memory-v1" or d["authority_contract"]["no_private_content"] is not True:
        raise ValueError("not approved synthetic source")
    return d,hashlib.sha256(raw).hexdigest()

def eligible(doc,scope):
    return doc["project"]==scope and doc["authority"] in ("accepted","advisory")

def make_levels(doc,level_enum):
    text=doc["text"]
    words=text.split()
    return {
        level_enum.ABSTRACT:f"{doc['id']} | "+ " ".join(words[:6]),
        level_enum.OVERVIEW:f"{doc['id']} | "+" ".join(words[:25]),
        level_enum.DETAIL:f"{doc['id']} | "+text,
    }

def db_for(source):
    db=sqlite3.connect(":memory:")
    db.execute("CREATE TABLE docs(id TEXT PRIMARY KEY, project TEXT, authority TEXT, text TEXT)")
    db.execute("CREATE VIRTUAL TABLE idx USING fts5(text, content='docs', content_rowid='rowid', tokenize='unicode61')")
    for doc in source["corpus"]:
        db.execute("INSERT INTO docs(id,project,authority,text) VALUES(?,?,?,?)",
                   (doc["id"],doc["project"],doc["authority"],doc["text"]))
        db.execute("INSERT INTO idx(rowid,text) SELECT rowid,text FROM docs WHERE id=?",(doc["id"],))
    db.commit()
    return db

def query_ids(db,text,scope):
    # Reuse existing FTS index as an explicit external retrieval control; it
    # is not a native OpenViking retrieval implementation or engine.
    tokens=[w for w in re.findall(r"[^\W_]+",text.lower()) if len(w)>1][:12]
    expr=" OR ".join('"'+w.replace('"','""')+'"' for w in tokens)
    if not expr:return []
    return [x[0] for x in db.execute(
        "SELECT docs.id FROM idx JOIN docs ON idx.rowid=docs.rowid "
        "WHERE idx MATCH ? AND docs.project=? AND docs.authority!='superseded' "
        "ORDER BY bm25(idx),docs.id LIMIT 3",(expr,scope))]

def page(source,level_enum,query,budget=MAX_BUDGET):
    if not 32<=budget<=4096:raise ValueError("unadmitted context-byte budget")
    scope=query.get("project")
    if scope!="atlas":raise ValueError("scope not admitted")
    db=db_for(source)
    try: ids=query_ids(db,query["query"],scope)
    finally:db.close()
    docs={d["id"]:d for d in source["corpus"]}
    source_items=[]
    for ident in ids:
        doc=docs[ident]
        if not eligible(doc,scope):raise ValueError("stale/foreign candidate")
        source_items.append((doc,make_levels(doc,level_enum)))
    # The owner/harness chooses ranking and which level to promote. Untrusted
    # model or memory must not change the catalog or choose authorization.
    selected=[]
    left=budget
    for doc,levels in source_items:
        level=level_enum.ABSTRACT
        payload=levels[level]
        cost=len(payload.encode("utf-8"))
        if cost>left:break
        left-=cost
        selected.append({"id":doc["id"],"level":level.value,"text":payload,
                         "digest":hashlib.sha256(doc["text"].encode()).hexdigest(),
                         "authority":doc["authority"],"scope":doc["project"],
                         "cost_bytes":cost})
    # Hot-promotion only from an already retained leaf. If enough headroom,
    # prefer full source record for strongest source-grounded reasoning.
    if selected:
        first=selected[0]
        doc=docs[first["id"]]
        if not eligible(doc,scope):raise ValueError("source scope changed")
        levels=make_levels(doc,level_enum)
        for newlevel in (level_enum.DETAIL,level_enum.OVERVIEW):
            text=levels[newlevel]
            delta=len(text.encode())-first["cost_bytes"]
            if delta<=left:
                first.update({"text":text,"level":newlevel.value,"cost_bytes":len(text.encode())})
                left-=delta
                break
    assert sum(i["cost_bytes"] for i in selected)+left==budget
    for record in selected:
        original=docs[record["id"]]
        if record["scope"]!="atlas" or original["authority"]=="superseded" or \
            record["digest"]!=hashlib.sha256(original["text"].encode()).hexdigest():
            raise ValueError("source custody lost at promotion")
    return selected,left

def self_test():
    src,sha=read_fixture()
    assert len(src["corpus"])==8
    assert len({d["id"] for d in src["corpus"]})==8
    try:page(src,None,{"project":"vega","query":"secret"})
    except ValueError:pass
    else:raise AssertionError("foreign project not denied")
    try:page(src,None,{"project":"atlas","query":"test"},budget=0)
    except ValueError:pass
    else:raise AssertionError("invalid budget not rejected")
    print("PASS synthetic fixture and scope/budget source critic; native upstream enum NOT_EXECUTED")

def run(out:Path,seed:int):
    native,hash_source=load_upstream_levels()
    original,hash_fixture=read_fixture()
    db=db_for(original)
    try:
        rows=[]
        for q in original["questions"]:
            chosen,left=page(original,native,q,budget=MAX_BUDGET)
            baseline=[{**x,"level":native.ABSTRACT.value,
                       "text":make_levels(next(d for d in original["corpus"] if d["id"]==x["id"]),native)[native.ABSTRACT]}
                       for x in chosen]
            positive=q["expect"] is not None
            rows.append({
                "query_id":q["id"],"positive":positive,
                "oracle_expected_id":q["expect"],
                "candidate_ids":[r["id"] for r in chosen],
                "correct_source_in_candidate":positive and q["expect"] in {r["id"] for r in chosen},
                "first_full_detail":bool(chosen and chosen[0]["level"]==native.DETAIL.value),
                "first_full_detail_matches_oracle":bool(chosen and chosen[0]["id"]==q["expect"] and chosen[0]["level"]==native.DETAIL.value),
                "negative_retrieval_nonabstention":not positive and bool(chosen),
                "scope_or_stale_exposure":any(x["scope"]!="atlas" or x["authority"]=="superseded" for x in chosen),
                "l0_only_bytes":sum(len(x["text"].encode()) for x in baseline),
                "actual_bytes":MAX_BUDGET-left,
            })
    finally:db.close()
    report={
        "schema":"hmrc-r5-source-native-contextlevel-and-independent-paging",
        "upstream_repo":"volcengine/OpenViking","source_commit":UPSTREAM_COMMIT,
        "source_blob":UPSTREAM_GIT_BLOB,"source_sha256":hash_source,
        "public_fixture_sha256":hash_fixture,
        "native_upstream_context_enum_executed":True,
        "native_vendor_hierarchical_retriever_executed":False,
        "native_vendor_storage_executed":False,
        "actual_own_scoped_level_pager_executed":True,
        "model_or_embedding_executed":False,
        "seed":seed,"byte_budget":MAX_BUDGET,"budget_units":TOKEN_COST_LABEL,
        "results":rows,
        "positive_detail_at_top":sum(x["first_full_detail_matches_oracle"] for x in rows),
        "negative_nonabstentions":sum(x["negative_retrieval_nonabstention"] for x in rows),
        "foreign_or_stale_exposure":sum(x["scope_or_stale_exposure"] for x in rows),
        "license":"AGPL-3.0: upstream code used transiently for qualification; integration/license approval NOT_GRANTED",
        "limitations":["original source fixture, not independent new task corpus",
                       "enum extraction executes only exact verified upstream class",
                       "FTS is separate SQLite reference, not OpenViking hierarchical retrieval",
                       "budget in UTF8 bytes, no model tokens, physical KV cache or task success",
                       "no native server/storage or full L0/L1/L2 generation",
                       "source-pinned upstream enum does not authorize derived pager"],
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False)+"\n")
    print("UPSTREAM_NATIVE_CONTEXTLEVEL=EXECUTED; OPENVIKING_RETRIEVER=NOT_RUN; HIERARCHICAL_OWNER_PAGER=EXECUTED")
    print("R5_HIERARCHY_SOURCE_METRICS="+json.dumps({
      "positive_top_detail":report["positive_detail_at_top"],
      "negative_nonabstentions":report["negative_nonabstentions"],
      "foreign_stale_exposure":report["foreign_or_stale_exposure"]},sort_keys=True))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--out",type=Path)
    p.add_argument("--seed",type=int,default=11)
    args=p.parse_args()
    if args.self_test:self_test()
    else:
        if not args.out:p.error("--out required")
        run(args.out,args.seed)
