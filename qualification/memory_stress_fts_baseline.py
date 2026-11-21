#!/usr/bin/env python3
"""Synthetic memory retrieval load screen, not an agent or vendor qualification.

Pure stdlib; fixed original public corpus, deterministic decoys and independent
scorer. No private DLE/CPE data, model, credentials, or source mutation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import time

FIXTURE = Path(__file__).with_name("fixtures") / "memory_dle_cpe_synthetic_v1.json"
SIZES = (100, 1000)
SEEDS = (11, 29, 47)
ALLOWED = {"accepted", "advisory"}
FIELDS = ("release authorization verifier", "blue signal canonical identity",
          "next executable source digest", "Observe Plan Apply Verify",
          "German blaues Signal", "Thai สัญญาณสีน้ำเงิน")


def load_fixture():
    content = FIXTURE.read_bytes()
    data = json.loads(content)
    assert data["schema"] == "synthetic-dle-cpe-memory-v1"
    assert data["authority_contract"]["no_private_content"] is True
    assert len(data["corpus"]) == len(data["questions"]) == 8
    return data, hashlib.sha256(content).hexdigest()


def make_decoys(size, seed):
    rng = random.Random(seed)
    result = []
    # Decoys intentionally resemble real questions; all are advisory,
    # originate outside Atlas, and may never be admitted as current authority.
    for n in range(size):
        topic = FIELDS[rng.randrange(len(FIELDS))]
        result.append({"id": f"SYN_STRESS_{seed}_{n:05d}",
                       "project": "other", "authority": "advisory",
                       "revision": 0, "text": f"Synthetic distractor {n}. {topic}. "
                       f"Unrelated archival sample not accepted Atlas source."})
    return result


def tokenizer(text):
    # FTS5 unicode61 indexes ASCII and Unicode. Explicitly quote tokens to
    # avoid syntax control through query content. Does not promise Thai word
    # segmentation; that is an observable limitation.
    import re
    return [v for v in re.findall(r"[^\\W_]+", text.casefold()) if len(v) > 1][:12]


def search(db, query, limit, scope):
    tokens = tokenizer(query)
    if not tokens:
        return []
    expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)
    sql = ("SELECT d.id FROM idx JOIN docs d ON d.rowid=idx.rowid "
           "WHERE idx MATCH ? ")
    params = [expression]
    if scope:
        sql += "AND d.project='atlas' AND d.authority!='superseded' "
    sql += "ORDER BY bm25(idx), d.id LIMIT ?"
    params.append(limit)
    return [r[0] for r in db.execute(sql, params)]


def execute(size, seed, source):
    docs = list(source["corpus"]) + make_decoys(size, seed)
    with tempfile.TemporaryDirectory(prefix="synthetic-memory-stress-") as root:
        db = sqlite3.connect(str(Path(root) / "fts.db"))
        try:
            db.execute("CREATE TABLE docs(id TEXT PRIMARY KEY, project TEXT, authority TEXT, text TEXT)")
            db.execute("CREATE VIRTUAL TABLE idx USING fts5(text, content='docs', content_rowid='rowid', tokenize='unicode61')")
            for d in docs:
                db.execute("INSERT INTO docs VALUES(?,?,?,?)",
                           (d["id"], d["project"], d["authority"], d["text"]))
                db.execute("INSERT INTO idx(rowid,text) SELECT rowid,text FROM docs WHERE id=?",
                           (d["id"],))
            db.commit()
            by_id = {d["id"]: d for d in docs}
            results = {}
            for treatment in ("raw", "source-scoped"):
                start = time.monotonic()
                scores = []
                for q in source["questions"]:
                    found = search(db, q["query"], 3, treatment == "source-scoped")
                    expected = q["expect"]
                    scores.append({
                        "query_id": q["id"], "positive": expected is not None,
                        "recall_at_3": (expected in found) if expected else None,
                        "top1": (found[0] == expected) if expected and found else False,
                        "negative_nonabstention": bool(found) if expected is None else None,
                        "foreign": any(by_id[x]["project"] != "atlas" for x in found),
                        "stale": any(by_id[x]["authority"] == "superseded" for x in found),
                    })
                positives = [s for s in scores if s["positive"]]
                negatives = [s for s in scores if not s["positive"]]
                results[treatment] = {
                    "positives": len(positives),
                    "recall_at_3": sum(s["recall_at_3"] for s in positives),
                    "top1": sum(s["top1"] for s in positives),
                    "negative_nonabstentions": sum(s["negative_nonabstention"] for s in negatives),
                    "foreign_exposures": sum(s["foreign"] for s in scores),
                    "stale_exposures": sum(s["stale"] for s in scores),
                    "queries": len(scores),
                    "wall_ms": round((time.monotonic() - start) * 1000, 3),
                    "probe_counts": scores,
                }
            assert results["source-scoped"]["foreign_exposures"] == 0
            assert results["source-scoped"]["stale_exposures"] == 0
            return results
        finally:
            db.close()


def self_test():
    fixture, _ = load_fixture()
    assert len(make_decoys(100, 11)) == 100
    assert make_decoys(100, 11) == make_decoys(100, 11)
    assert make_decoys(100, 11) != make_decoys(100, 29)
    assert len({d["id"] for d in make_decoys(1000, 47)}) == 1000
    assert tokenizer("Thai สัญญาณสีน้ำเงิน")
    tiny = execute(100, 11, fixture)
    assert tiny["source-scoped"]["foreign_exposures"] == 0
    assert tiny["source-scoped"]["stale_exposures"] == 0
    print("PASS synthetic stress contract, negative isolation and deterministic source")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path)
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return
    if not a.out:
        p.error("--out required")
    fixture, digest = load_fixture()
    rows = []
    for size in SIZES:
        for seed in SEEDS:
            rows.append({"distractors": size, "seed": seed, "treatments": execute(size, seed, fixture)})
    receipt = {
        "schema": "memory-cpu-stress-v1", "source_fixture_sha256": digest,
        "source_sha": "source-only-experiment", "replicates_per_scale": len(SEEDS),
        "native_vendor_executed": False, "llm_inference_executed": False,
        "agent_task_accepted": False, "memory_effectiveness_qualified": False,
        "synthetic_only": True, "authority_promoted": False,
        "limitations": ["No embedding/reranker", "FTS unicode61 Thai segmentation limited",
                        "No realistic language-model behavior", "No task success inference",
                        "Source-scoped query uses authoritative metadata as external filter",
                        "Timing tiny corpus host-specific"],
        "rows": rows,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print("PASS 6 paired source-only SQLite FTS5 stress replicates; model/agent NOT_RUN")


if __name__ == "__main__":
    main()
