#!/usr/bin/env python3
"""Verify downloaded Heretic/base Safetensors against admitted pinned public OIDs.

Reads only explicitly designated local files. Does not fetch, import, or run models.
Success attests weight bytes only; it never qualifies an actor or inference route.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path

SCHEMA = "heretic-weight-byte-verification/v1"
SOURCE_SCHEMA = "heretic-source-observation/v1"
MAX_RECEIPT_BYTES = 128 * 1024
HEX64 = re.compile(r"^[a-f0-9]{64}$")
HEX40 = re.compile(r"^[a-f0-9]{40}$")
SHARD = re.compile(r"^model-\d{5}-of-\d{5}\.safetensors$")
ALLOWED_PAIRS = {
    "lfm-2.6b": ("LiquidAI/LFM2.5-2.6B", "heretic-org/LFM-2.5-2.6B-heretic"),
    "qwen-4b-instruct": ("Qwen/Qwen3-4B-Instruct-2507", "heretic-org/Qwen3-4B-Instruct-2507-heretic"),
}

class Denied(Exception):
    pass

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def strict_json(data: bytes) -> object:
    def no_dupes(items: list[tuple[str, object]]) -> dict:
        obj = {}
        for key, value in items:
            if key in obj:
                raise Denied("RECEIPT_DUPLICATE_KEYS")
            obj[key] = value
        return obj
    def no_constants(_: str):
        raise Denied("RECEIPT_NONFINITE_JSON")
    try:
        return json.loads(data, object_pairs_hook=no_dupes, parse_constant=no_constants)
    except (UnicodeError, ValueError) as exc:
        raise Denied("RECEIPT_INVALID_JSON") from exc

def load_receipt(path: Path, expected_digest: str) -> dict:
    if not HEX64.fullmatch(expected_digest):
        raise Denied("RECEIPT_DIGEST_UNPINNED")
    if path.is_symlink() or not path.is_file():
        raise Denied("RECEIPT_FILE_UNTRUSTED")
    with path.open("rb") as f:
        raw = f.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise Denied("RECEIPT_OVERSIZED")
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise Denied("RECEIPT_DIGEST_MISMATCH")
    doc = strict_json(raw)
    if not isinstance(doc, dict) or doc.get("schema") != SOURCE_SCHEMA or doc.get("campaign") != "model-spelunker-189":
        raise Denied("SOURCE_RECEIPT_SCHEMA_DENIED")
    scope = doc.get("scope_limits")
    if not isinstance(scope, dict) or scope.get("source_only") is not True:
        raise Denied("SOURCE_SCOPE_DENIED")
    return doc

def target_shards(doc: dict, pair: str, variant: str, expected_revision: str) -> tuple[str, list[dict]]:
    if pair not in ALLOWED_PAIRS or variant not in ("base", "modified"):
        raise Denied("MODEL_VARIANT_NOT_ALLOWED")
    if not HEX40.fullmatch(expected_revision):
        raise Denied("MODEL_REVISION_UNPINNED")
    names = ALLOWED_PAIRS[pair]
    model_id = names[0 if variant == "base" else 1]
    entries = doc.get("pair_reports")
    manifests = doc.get("publisher_file_manifests")
    if not isinstance(entries, list) or not isinstance(manifests, list):
        raise Denied("SOURCE_RECEIPT_STRUCTURE_DENIED")
    matching_pairs = [v for v in entries if isinstance(v, dict) and v.get("experiment_pair") == pair]
    matching = [v for v in manifests if isinstance(v, dict) and v.get("model") == model_id]
    if len(matching_pairs) != 1 or len(matching) != 1:
        raise Denied("SOURCE_RECEIPT_CARDINALITY_DENIED")
    report = matching_pairs[0]
    original = report.get(variant)
    if (report.get("source_gate") != "METADATA_READY_ONLY" or
        report.get("actor_qualification") != "UNKNOWN_NOT_EXECUTED" or
        report.get("inference_calls") != 0 or
        not isinstance(original, dict) or original.get("id") != model_id or
        original.get("observed_revision") != expected_revision or
        original.get("expected_revision") != expected_revision or
        original.get("holds") != [] or
        matching[0].get("revision") != expected_revision):
        raise Denied("SOURCE_IDENTITY_OR_GATE_DENIED")
    shards = matching[0].get("weights")
    if not isinstance(shards, list) or not shards or len(shards) != original.get("safetensors_file_count"):
        raise Denied("SHARD_CATALOG_MISMATCH")
    seen = set()
    for row in shards:
        if not isinstance(row, dict):
            raise Denied("SHARD_ENTRY_INVALID")
        name, size, oid = row.get("path"), row.get("size"), row.get("oid_sha256")
        if (not isinstance(name, str) or not SHARD.fullmatch(name) or name in seen or
            type(size) is not int or not 0 < size < 16 * 1024**3 or
            not isinstance(oid, str) or not HEX64.fullmatch(oid)):
            raise Denied("SHARD_ENTRY_INVALID")
        seen.add(name)
    return model_id, shards

def verify_local_files(doc: dict, pair: str, variant: str, expected_revision: str,
                       model_dir: Path, receipt_sha256: str) -> dict:
    model_id, shards = target_shards(doc, pair, variant, expected_revision)
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise Denied("MODEL_DIRECTORY_UNTRUSTED")
    known = {x["path"] for x in shards}
    discovered = {x.name for x in model_dir.iterdir() if x.name.endswith(".safetensors")}
    if discovered != known:
        raise Denied("SHARD_SET_MISMATCH")
    total = 0
    for row in shards:
        path = model_dir / row["path"]
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise Denied("SHARD_NOT_REGULAR_FILE")
        if path.stat().st_size != row["size"]:
            raise Denied("SHARD_SIZE_MISMATCH")
        if sha256_file(path) != row["oid_sha256"]:
            raise Denied("SHARD_BYTES_MISMATCH")
        total += row["size"]
    return {
        "schema": SCHEMA,
        "status": "LOCAL_WEIGHT_BYTES_ATTESTED_ONLY",
        "campaign": "model-spelunker-189",
        "pair": pair,
        "variant": variant,
        "model_id": model_id,
        "revision": expected_revision,
        "publisher_receipt_sha256": receipt_sha256,
        "shard_count": len(shards),
        "total_verified_bytes": total,
        "model_loaded": False,
        "actor_qualification": "UNKNOWN_NOT_EXECUTED",
        "runtime_gate": "HOLD_UNTIL_ADMITTED_VENUE_AND_VERIFIED_RUNTIME",
    }

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--receipt", required=True, type=Path)
    p.add_argument("--receipt-sha256", required=True)
    p.add_argument("--pair", required=True, choices=sorted(ALLOWED_PAIRS))
    p.add_argument("--variant", required=True, choices=("base", "modified"))
    p.add_argument("--revision", required=True)
    p.add_argument("--model-dir", required=True, type=Path)
    a = p.parse_args(argv)
    try:
        doc = load_receipt(a.receipt, a.receipt_sha256)
        result = verify_local_files(doc, a.pair, a.variant, a.revision,
                                    a.model_dir, a.receipt_sha256)
    except (Denied, OSError, TypeError, ValueError) as exc:
        # Never print local file paths, weight contents or arbitrary provider errors.
        klass = str(exc) if isinstance(exc, Denied) else "IO_OR_INPUT_DENIED"
        print(json.dumps({"schema": SCHEMA, "status": "HOLD", "reason": klass,
                          "actor_qualification": "UNKNOWN_NOT_EXECUTED"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
