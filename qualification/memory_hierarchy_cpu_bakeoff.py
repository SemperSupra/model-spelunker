#!/usr/bin/env python3
"""Public synthetic DLE/CPE CPU memory experiment; vendor adapters only.

No LLM, private source, CPE promotion, agent-task oracle, or production routing.
Every native retrieval is scored separately from the authority-selection rule.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

FIXTURE = Path(__file__).parent / "fixtures" / "memory_dle_cpe_synthetic_v1.json"
MARKER = re.compile(r"SYN_(?:ATLAS|VEGA)_[A-Z0-9_]+")
VALID = {"control", "engram", "reme", "openviking-source"}
STOP_TIMEOUT = 35


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_fixture() -> dict:
    raw = FIXTURE.read_bytes()
    data = json.loads(raw)
    validate_fixture(data)
    return data


def validate_fixture(data: dict) -> None:
    if data.get("schema") != "synthetic-dle-cpe-memory-v1":
        raise ValueError("unknown fixture schema")
    docs, questions = data["corpus"], data["questions"]
    if len(docs) != 8 or len(questions) != 8:
        raise ValueError("incomplete frozen corpus")
    ids = {d["id"] for d in docs}
    if len(ids) != len(docs):
        raise ValueError("duplicate synthetic authority IDs")
    for d in docs:
        if d["project"] not in ("atlas", "vega"):
            raise ValueError("unapproved project")
        if d["authority"] not in ("accepted", "superseded", "advisory"):
            raise ValueError("unaccepted authority status")
        if not d["id"].startswith("SYN_" + d["project"].upper() + "_"):
            raise ValueError("source ID/project conflict")
    for q in questions:
        if q["project"] != "atlas":
            raise ValueError("only atlas may be queried")
        if q["expect"] is not None and q["expect"] not in ids:
            raise ValueError("unknown expected source")
        if q["expect"] is not None:
            d = next(d for d in docs if d["id"] == q["expect"])
            if d["project"] != "atlas" or d["authority"] == "superseded":
                raise ValueError("invalid accepted expectation")
    if not data["authority_contract"].get("no_private_content"):
        raise ValueError("private data cannot run on public GHA")


def run_cmd(args, env, cwd, timeout=STOP_TIMEOUT):
    start = time.monotonic()
    p = subprocess.run(args, env=env, cwd=cwd, capture_output=True,
                       timeout=timeout, text=True, check=False)
    if p.returncode:
        msg = (p.stderr or p.stdout)[-420:]
        raise RuntimeError(f"native CLI exit={p.returncode} command={args[0:2]!r} err_tail={msg!r}")
    return p.stdout, int((time.monotonic()-start)*1000)


def http_json(port: int, endpoint: str, payload: dict, timeout=20):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/{endpoint}", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as result:
        body = result.read(131072)
        if result.status != 200:
            raise RuntimeError(f"vendor HTTP status={result.status}")
    return body.decode("utf-8", errors="replace"), int((time.monotonic()-start)*1000)


def records(body: str) -> list[str]:
    return list(dict.fromkeys(MARKER.findall(body)))


def authority_guard(ids: list[str], fixture: dict, project: str) -> dict:
    """Separate external reconciler. This is NOT native memory policy enforcement."""
    source = {d["id"]: d for d in fixture["corpus"]}
    eligible = [source[i] for i in ids if i in source and
                source[i]["project"] == project and
                source[i]["authority"] in ("accepted", "advisory")]
    rejected = [i for i in ids if i not in source or source[i]["project"] != project or
                source[i]["authority"] == "superseded"]
    return {
        "advisory_candidates_accepted": [d["id"] for d in eligible],
        "excluded_non_authoritative": rejected,
        "memory_promoted_to_dle_or_cpe": False,
    }


def query_result(query: dict, body: str, ms: int, fixture: dict) -> dict:
    found = records(body)
    guard = authority_guard(found, fixture, query["project"])
    expected = query["expect"]
    return {
        "id": query["id"], "kind": query["type"],
        "observed_ms": ms, "returned_bytes": len(body.encode("utf-8")),
        "returned_sha256": sha_bytes(body.encode("utf-8")),
        "source_ids_seen": found[:20],
        "expected_source_recalled": expected in found if expected else None,
        "cross_project_source_seen": any(x.startswith("SYN_VEGA_") for x in found),
        "superseded_source_seen": any("R7_RELEASE" in x or "R4_BLUE" in x for x in found),
        "guard": guard,
    }


def engram(fixture, tmp: Path) -> tuple[list[dict], dict]:
    env = dict(os.environ, ENGRAM_DATA_DIR=str(tmp / "engram"),
               HOME=str(tmp / "home"), ENGRAM_PROJECT="atlas",
               NO_COLOR="1", CI="true")
    (tmp / "home").mkdir()
    (tmp / "engram").mkdir()
    binary = os.environ.get("ENGRAM_BIN", "engram")
    version, _ = run_cmd([binary, "version"], env, tmp)
    writes = []
    for doc in fixture["corpus"]:
        body = "SOURCE_ID=" + doc["id"] + "; rev=" + str(doc["revision"]) + \
               "; authority=" + doc["authority"] + ". " + doc["text"]
        _, elapsed = run_cmd([binary, "save", doc["id"], body,
                               "--project", doc["project"]], env, tmp)
        writes.append(elapsed)
    output = []
    for question in fixture["questions"]:
        raw, elapsed = run_cmd([binary, "search", question["query"],
                                "--project", question["project"]], env, tmp)
        output.append(query_result(question, raw, elapsed, fixture))
    return output, {"native_write_count":len(writes),
                    "native_write_ms_total":sum(writes),
                    "vendor_version_output_sha256":sha_bytes(version.encode()),
                    "atlas_and_vega_saved_in_same_local_sqlite":True}


def reme(fixture, tmp: Path) -> tuple[list[dict], dict]:
    env = dict(os.environ, HOME=str(tmp / "home"), NO_COLOR="1",
               CI="true", PYTHONDONTWRITEBYTECODE="1")
    (tmp / "home").mkdir()
    port = 18444
    workspace = tmp / "atlas"
    workspace.mkdir()
    log = (tmp / "reme.log").open("w")
    proc = subprocess.Popen(["reme", "start", "workspace_dir="+str(workspace),
                             "service.port="+str(port), "service.web_enabled=false"],
                            env=env, cwd=tmp, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                # Categorize public-synthetic startup failure without uploading raw server logs.
                log.flush()
                sample=(tmp / "reme.log").read_text(encoding="utf-8",errors="replace")
                errors=re.findall(r"(?:ModuleNotFoundError|ImportError|RuntimeError|ValueError|TypeError|AttributeError|FileNotFoundError):[^\\n]{0,180}",sample)
                category=errors[-1][:190] if errors else "uncategorized"
                raise RuntimeError("ReMe exited during local startup; category="+category)
            try:
                http_json(port, "version", {}, timeout=2)
                break
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(1)
        else:
            raise RuntimeError("ReMe loopback service not ready in 75 seconds")
        writes = []
        for doc in fixture["corpus"]:
            if doc["project"] != "atlas":
                continue  # ReMe uses a separate workspace per source project.
            content = ("SOURCE_ID="+doc["id"]+"; rev="+str(doc["revision"])+
                       "; authority="+doc["authority"]+". "+doc["text"])
            _, ms = http_json(port, "write", {
                "path":"digest/wiki/"+doc["id"].lower(),
                "name":doc["id"], "description":doc["domain"],
                "content":content}, timeout=30)
            writes.append(ms)
        # A writer or watcher may need time to index derived BM25.
        settle_ms = 0
        for attempt in range(12):
            body, _ = http_json(port, "search", {"query":"Atlas admission signed release",
                                                  "limit":8})
            if "SYN_ATLAS_DLE_R8_HOLD" in body:
                break
            time.sleep(1)
            settle_ms += 1000
        output = []
        for q in fixture["questions"]:
            body, ms = http_json(port, "search", {"query":q["query"],"limit":8})
            output.append(query_result(q, body, ms, fixture))
        return output, {"native_write_count":len(writes),
                        "native_write_ms_total":sum(writes),
                        "bm25_index_settle_ms":settle_ms,
                        "project_workspace_isolation":"one workspace per project",
                        "isolated_vega_workspace_not_opened_in_atlas_process":True}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log.close()


def openviking_source(upstream: Path) -> dict:
    """Check *real upstream source contract*, not a substituted memory engine."""
    doc = upstream / "docs" / "en" / "concepts" / "03-context-layers.md"
    text = doc.read_text(encoding="utf-8")
    terms = (".abstract.md", ".overview.md", "L0", "L1", "L2",
             "256 characters", "4000 characters")
    missed = [t for t in terms if t not in text]
    if missed:
        raise RuntimeError("upstream OpenViking structural contract changed")
    return {
        "backend":"openviking-source",
        "native_memory_retrieval_executed":False,
        "source_structure_verified":True,
        "source_docs_sha256":sha_bytes(doc.read_bytes()),
        "status":"SOURCE_ONLY_NOT_A_RUNTIME_BAKEOFF",
        "required_provider":"local VLM/embeddings and native RAGFS client unqualified",
        "memory_promoted_to_dle_or_cpe":False,
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--backend",choices=sorted(VALID))
    parser.add_argument("--out")
    parser.add_argument("--upstream")
    parser.add_argument("--self-test", action="store_true")
    args=parser.parse_args()
    fixture=load_fixture()
    if args.self_test:
        # Two negative cases must be rejected before any backend execution.
        wrong=json.loads(json.dumps(fixture))
        wrong["corpus"][0]["authority"]="admin"
        try: validate_fixture(wrong)
        except ValueError: pass
        else: raise AssertionError("bad status admitted")
        wrong=json.loads(json.dumps(fixture))
        wrong["questions"][0]["expect"]="SYN_ATLAS_DLE_R7_RELEASE"
        try: validate_fixture(wrong)
        except ValueError: pass
        else: raise AssertionError("superseded authority expected")
        guard=authority_guard(["SYN_ATLAS_DLE_R7_RELEASE","SYN_ATLAS_DLE_R8_HOLD",
                               "SYN_VEGA_DLE_R3_SECRET"],fixture,"atlas")
        assert guard["advisory_candidates_accepted"]==["SYN_ATLAS_DLE_R8_HOLD"]
        assert len(guard["excluded_non_authoritative"])==2
        assert guard["memory_promoted_to_dle_or_cpe"] is False
        print("PASS source-only synthetic DLE/CPE authority, stale and tenant negative tests")
        return
    if not args.out or not args.backend:
        parser.error("--backend and --out required unless --self-test")
    receipt={
        "schema":"dle-cpe-cpu-memory-bakeoff-v1",
        "backend":args.backend,
        "fixture_sha256":sha_bytes(FIXTURE.read_bytes()),
        "source_commit":os.environ.get("BAKEOFF_SOURCE_SHA","unknown"),
        "model_inference_executed":False,
        "agent_task_accepted":False,
        "public_only_synthetic":True,
        "dle_cpe_authority_unchanged":True,
        "native_memory_retrieval_executed":False,
        "status":"UNKNOWN"
    }
    start=time.monotonic()
    try:
        if args.backend=="openviking-source":
            if not args.upstream: raise ValueError("--upstream required")
            receipt.update(openviking_source(Path(args.upstream)))
        elif args.backend=="control":
            receipt.update(status="CONTROL_NO_MEMORY",results=[],native_memory_retrieval_executed=False)
        else:
            with tempfile.TemporaryDirectory(prefix="memory-cpu-bakeoff-") as tmp:
                fn=engram if args.backend=="engram" else reme
                results, meta=fn(fixture,Path(tmp))
            positives=[r for r in results if r["expected_source_recalled"] is not None]
            false_leaks=[r["id"] for r in results if r["cross_project_source_seen"]]
            receipt.update(results=results,meta=meta,native_memory_retrieval_executed=True,
                           positives=len(positives),
                           recalled=sum(1 for r in positives if r["expected_source_recalled"]),
                           cross_project_leak_queries=false_leaks,
                           status="PASS_NATIVE_ADAPTER" if not false_leaks else "FAIL_PROJECT_SCOPE")
    except Exception as exc:
        # A failure is an integration result, not a negative model competence result.
        receipt.update(status="INTEGRATION_FAILURE",
                       failure_type=type(exc).__name__,
                       failure_detail=str(exc)[-300:])
    receipt["wall_ms"]=int((time.monotonic()-start)*1000)
    receipt["child_peak_rss_kib"]=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(receipt,sort_keys=True,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({k:receipt.get(k) for k in
                      ("backend","status","recalled","positives",
                       "cross_project_leak_queries","wall_ms")},sort_keys=True))
    if receipt["status"] in ("INTEGRATION_FAILURE","FAIL_PROJECT_SCOPE"):
        raise SystemExit(1)


if __name__=="__main__":
    main()
