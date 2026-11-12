#!/usr/bin/env python3
"""Thin, bounded Model Artifact Foundry hydration sidecar.

This wrapper NEVER chooses, approves, downloads from HF, or republishes models.
It delegates actual OCI hydration and verified durable selection to the existing
Model Artifact Foundry tools/hydrate.py, pinned at the image's source commit.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HEX = re.compile(r"^sha256:[0-9a-f]{64}$")
ID = re.compile(r"^[a-z0-9][a-z0-9._/-]{2,127}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
MAX_CATALOG = 1024 * 1024
MAF_TOOL = Path("/opt/maf/tools/hydrate.py")
ORAS = Path("/usr/local/bin/oras")
MAX_MODELS = 40

class Hold(ValueError):
    pass

def load_catalog(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise Hold("APPROVED_CATALOG_UNTRUSTED")
    with path.open("rb") as f:
        raw = f.read(MAX_CATALOG + 1)
    if len(raw) > MAX_CATALOG:
        raise Hold("APPROVED_CATALOG_TOO_LARGE")
    def no_duplicates(rows):
        out = {}
        for key, value in rows:
            if key in out: raise Hold("CATALOG_DUPLICATE_FIELD")
            out[key] = value
        return out
    try:
        data = json.loads(raw, object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, Hold): raise
        raise Hold("CATALOG_INVALID_JSON") from exc
    if (not isinstance(data, dict) or set(data) != {"schema_version", "artifacts"} or
        data["schema_version"] != 1 or type(data["artifacts"]) is not dict or
        len(data["artifacts"]) > MAX_MODELS):
        raise Hold("APPROVED_CATALOG_SCHEMA")
    return data

def selection(catalog: dict, logical_id: str, expected_digest: str) -> dict:
    if not isinstance(logical_id, str) or not ID.fullmatch(logical_id):
        raise Hold("LOGICAL_ID_INVALID")
    if not isinstance(expected_digest, str) or not HEX.fullmatch(expected_digest):
        raise Hold("EXACT_APPROVED_DIGEST_REQUIRED")
    entry = catalog["artifacts"].get(logical_id)
    if not isinstance(entry, dict):
        raise Hold("MODEL_NOT_APPROVED")
    mandatory = {"oci_repository","approved_digest","candidate_evidence",
                 "upstream_exact_revision","license_spdx_id","approved_at"}
    if not mandatory <= set(entry) or not set(entry) <= mandatory | {"compatibility","previous_digests"}:
        raise Hold("APPROVED_ENTRY_SCHEMA")
    evidence = entry["candidate_evidence"]
    if (type(evidence) is not dict or set(evidence) !=
        {"repository","commit_sha","manifest_path"} or not SHA40.fullmatch(
            str(evidence.get("commit_sha","")))):
        raise Hold("CANDIDATE_PROVENANCE_UNPINNED")
    repo = entry["oci_repository"]
    if (not isinstance(repo,str) or not repo.startswith("ghcr.io/sempersupra/") or
        not re.fullmatch(r"ghcr\.io/sempersupra/[a-z0-9][a-z0-9._/-]*", repo)):
        raise Hold("OCI_REPOSITORY_POLICY_DENIED")
    if (entry["approved_digest"] != expected_digest or
        not isinstance(entry["license_spdx_id"],str) or not entry["license_spdx_id"] or
        not isinstance(entry["upstream_exact_revision"],str) or
        not isinstance(entry["approved_at"],str) or not entry["approved_at"]):
        raise Hold("MODEL_DIGEST_OR_APPROVAL_MISMATCH")
    return {"schema":"conditioning-hydration-selection/v1",
            "logical_id":logical_id,"oci_reference":repo+"@"+expected_digest,
            "approved_digest":expected_digest,"candidate_commit":evidence["commit_sha"],
            "state":"APPROVED_CATALOG_ENTRY_RESOLVED_ONLY",
            "file_bytes_verified":False,"hydration_executed":False}

def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--id",dest="logical_id",required=True)
    p.add_argument("--approved-digest",required=True)
    p.add_argument("--cache-root",type=Path,default=Path("/model-cache"))
    p.add_argument("--hydrate",action="store_true",help="Call pinned MAF hydrator with pinned ORAS CLI")
    opts=p.parse_args(argv)
    try:
        doc=load_catalog(opts.catalog)
        result=selection(doc,opts.logical_id,opts.approved_digest)
        if opts.hydrate:
            if not MAF_TOOL.is_file() or not ORAS.is_file():
                raise Hold("PINNED_MAF_HYDRATOR_UNAVAILABLE")
            if opts.cache_root.is_symlink() or not opts.cache_root.is_dir():
                raise Hold("MOUNTED_CONTENT_STORE_REQUIRED")
            cmd=[sys.executable,str(MAF_TOOL),"--catalog",str(opts.catalog),
                 "--id",opts.logical_id,"--cache-root",str(opts.cache_root),"--oras",str(ORAS)]
            # Preserve the upstream Foundry contract and its complete verification.
            subprocess.run(cmd,check=True,timeout=60*45)
            result["state"]="DELEGATED_TO_PINNED_MAF_HYDRATOR"
            # An external verifier must read the MAF receipt and verified byte tree.
            # Do not turn the wrapper's subprocess success into quality or HIL admission.
            result["hydration_executed"]=True
        print(json.dumps(result,sort_keys=True))
        return 0
    except (Hold,OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
        code=str(exc) if isinstance(exc,Hold) else "HYDRATION_EXECUTION_OR_IO_HOLD"
        print(json.dumps({"status":"HOLD","reason":code,"hydration_executed":False}))
        return 2
if __name__=="__main__":
    sys.exit(main())
