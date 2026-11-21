#!/usr/bin/env python3
"""Pinned-source observation critic; never launches agents or grants authority.

Optional independent source check fetches *immutable* upstream GitHub file
URLs and validates exact Git blob identities, not HEAD or tag aliases.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
SAFE = re.compile(r"[a-zA-Z0-9._/-]+\Z")
ALLOWED = {"pi", "opencode", "aider"}
SOURCES = {"pi": "earendil-works/pi", "opencode": "anomalyco/opencode",
           "aider": "Aider-AI/aider"}

def verify(x):
    if not isinstance(x, dict) or set(x) != {
        "schema", "authority", "runtime_qualified", "production_admitted", "candidates"}:
        raise ValueError("unexpected top-level schema")
    if x["schema"] != "agent-harness-interface-source-census/v1" or x["authority"] != "PUBLIC_SOURCE_ONLY":
        raise ValueError("wrong evidence scope")
    if x["runtime_qualified"] is not False or x["production_admitted"] is not False:
        raise ValueError("source cannot qualify runtime or production")
    candidates = x["candidates"]
    if not isinstance(candidates, list) or {c["id"] for c in candidates} != ALLOWED or len(candidates) != 3:
        raise ValueError("incomplete or duplicate candidate set")
    for c in candidates:
        if set(c) != {"id", "upstream", "aliases", "source_commit", "source_files",
                      "human", "automation", "agent", "caveats"}:
            raise ValueError("unknown candidate field")
        if c["upstream"] != SOURCES[c["id"]] or not HEX40.fullmatch(c["source_commit"]):
            raise ValueError("unpinned source or redirected alias")
        if not isinstance(c["aliases"], list) or any(not isinstance(v, str) or
                  not SAFE.fullmatch(v) for v in c["aliases"]):
            raise ValueError("invalid aliases")
        if not isinstance(c["source_files"], list) or not c["source_files"]:
            raise ValueError("no source evidence")
        for f in c["source_files"]:
            if set(f) != {"path", "blob_sha", "surface", "proof"}:
                raise ValueError("invalid evidence fields")
            if (not isinstance(f["path"], str) or not SAFE.fullmatch(f["path"]) or
                ".." in Path(f["path"]).parts or f["path"].startswith("/")):
                raise ValueError("unsafe source path")
            if not HEX40.fullmatch(f["blob_sha"]) or f["proof"] != "SOURCE_OBSERVED":
                raise ValueError("unverified source blob")
            if f["surface"] not in {"jsonl-rpc", "http-api-source", "sdk-source",
                                     "scripted-cli-source"}:
                raise ValueError("unknown surface")
        if c["agent"] != "ADAPTER_REQUIRED_UNVERIFIED":
            raise ValueError("unproven MCP or agent invocation")
        if c["id"] == "aider" and c["automation"] != "CLI_SOURCE_UNADMITTED":
            raise ValueError("unsafe Aider auto-approval assumption")
        if not c["human"].endswith("_SOURCE") or not isinstance(c["caveats"], list) or not c["caveats"]:
            raise ValueError("missing audience/provenance caveats")
    return {"schema": "agent-source-interface-critic/v1", "result": "SOURCE_ONLY_VALID",
            "candidates": 3, "runtime_qualified": False, "production_admitted": False}

def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def online_verify(x):
    verified = []
    for c in x["candidates"]:
        for f in c["source_files"]:
            repo, commit, path = c["upstream"], c["source_commit"], f["path"]
            url = "https://raw.githubusercontent.com/" + repo + "/" + commit + "/" + path
            req = urllib.request.Request(url, headers={"User-Agent": "actor-census-source-proof/1"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                if resp.status != 200:
                    raise ValueError("unavailable immutable upstream file")
                data = resp.read(524289)
            if len(data) > 524288:
                raise ValueError("over-budget pinned source")
            if blob_sha(data) != f["blob_sha"]:
                raise ValueError("pinned upstream blob drift: " + c["id"])
            verified.append(c["id"] + ":" + f["surface"])
    return verified

def selftest(x):
    verify(x)
    changes = [
        lambda d: d.update(production_admitted=True),
        lambda d: d.update(runtime_qualified=True),
        lambda d: d["candidates"][0].update(source_commit="latest"),
        lambda d: d["candidates"][0].update(upstream="badlogic/pi-mono"),
        lambda d: d["candidates"][1].update(agent="MCP_NATIVE"),
        lambda d: d["candidates"][2].update(automation="CLI_NATIVE_SAFE"),
        lambda d: d["candidates"][1]["source_files"][0].update(blob_sha="0"*40),
        lambda d: d["candidates"][0]["source_files"][0].update(path="../private"),
        lambda d: d["candidates"].pop(),
        lambda d: d["candidates"].append(copy.deepcopy(d["candidates"][0])),
    ]
    for n, change in enumerate(changes):
        bad = copy.deepcopy(x)
        change(bad)
        try: verify(bad)
        except (ValueError, KeyError, TypeError):
            continue
        raise AssertionError("mutant not rejected: " + str(n))
    return {"negative_controls": len(changes), "status": "PASS", "network": False}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["self-test", "verify", "source-verify"])
    args = p.parse_args()
    x = json.loads((HERE/"interface_source_census.json").read_text(encoding="utf-8"))
    if args.action == "self-test":
        print(json.dumps(selftest(x), sort_keys=True))
    elif args.action == "source-verify":
        verify(x)
        print(json.dumps({"scope": "SOURCE_ONLY", "verified_source_blobs": online_verify(x)},
                         sort_keys=True))
    else:
        print(json.dumps(verify(x), sort_keys=True))
if __name__ == "__main__":
    main()
