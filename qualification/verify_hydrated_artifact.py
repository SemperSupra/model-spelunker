#!/usr/bin/env python3
"""Verify a hydrated harness payload against its durable admission/build receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return "sha256:"+h.hexdigest()


def verify(root: Path, admission: dict, manifest_digest: str | None=None) -> int:
    if admission["admission"]["state"]!="BUILD_ADMITTED":
        raise ValueError("artifact is not BUILD_ADMITTED")

    expected_manifest=admission["artifact"]["digest"]
    if manifest_digest and manifest_digest!=expected_manifest:
        raise ValueError(
            f"manifest digest mismatch: {manifest_digest} != {expected_manifest}"
        )

    artifact_root=root/"artifact"
    build_receipt=artifact_root/"build-receipt.json"
    if not build_receipt.is_file():
        raise ValueError("missing embedded build receipt")

    expected_build=admission["artifact"]["build_receipt_digest"]
    actual_build=sha256_file(build_receipt)
    if actual_build!=expected_build:
        raise ValueError(f"build receipt digest mismatch: {actual_build} != {expected_build}")

    receipt=json.loads(build_receipt.read_text(encoding="utf-8"))
    if receipt["harness"]["name"]!=admission["harness"]["name"]:
        raise ValueError("harness name mismatch")

    checked=0
    for row in receipt["payload"]["files"]:
        path=artifact_root/row["path"]
        if not path.is_file():
            raise ValueError(f"missing payload file: {row['path']}")
        if path.stat().st_size!=row["bytes"]:
            raise ValueError(f"payload size mismatch: {row['path']}")
        actual=sha256_file(path).removeprefix("sha256:")
        if actual!=row["sha256"]:
            raise ValueError(f"payload digest mismatch: {row['path']}")
        checked+=1

    if checked==0:
        raise ValueError("embedded build receipt has no payload files")
    return checked



def verify_embedded(root: Path, manifest_digest: str, expected_digest: str,
                    harness: str, source_revision: str, realization_digest: str,
                    python_abi: str) -> int:
    """Independently check OCI transport; NOT a build-admission decision."""
    if manifest_digest != expected_digest:
        raise ValueError("sovereign OCI manifest digest mismatch")
    artifact_root = root.resolve() / "artifact"
    receipt_path = artifact_root / "build-receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError("missing or symlinked embedded build receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("record_type") != "harness-build-receipt":
        raise ValueError("invalid embedded build receipt")
    if receipt.get("harness", {}).get("name") != harness:
        raise ValueError("embedded harness identity mismatch")
    if receipt.get("source", {}).get("revision") != source_revision:
        raise ValueError("embedded source revision mismatch")
    config = receipt.get("build", {}).get("configuration", {})
    if config.get("realization", {}).get("profile_digest") != realization_digest:
        raise ValueError("embedded realization digest mismatch")
    if config.get("python_abi") != python_abi:
        raise ValueError("embedded Python ABI mismatch")
    rows = receipt.get("payload", {}).get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty embedded payload")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("invalid embedded payload row")
        rel = Path(row["path"])
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise ValueError("unsafe embedded payload path")
        if rel.as_posix() in seen:
            raise ValueError("duplicate embedded payload path")
        seen.add(rel.as_posix())
        path = artifact_root / rel
        if path.is_symlink() or not path.is_file() or artifact_root not in path.resolve().parents:
            raise ValueError("embedded payload escapes artifact root")
        size = row.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("invalid embedded payload size")
        if path.stat().st_size != size:
            raise ValueError("embedded payload size mismatch")
        if sha256_file(path) != "sha256:" + str(row.get("sha256", "")):
            raise ValueError("embedded payload digest mismatch")
    return len(rows)


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("root",type=Path)
    parser.add_argument("admission",type=Path,nargs="?")
    parser.add_argument("--expected-oci-digest")
    parser.add_argument("--expected-harness")
    parser.add_argument("--expected-source-revision")
    parser.add_argument("--expected-realization-digest")
    parser.add_argument("--expected-python-abi")
    parser.add_argument("--manifest-digest")
    args=parser.parse_args()

    if args.admission is None:
        expectations=[
            args.manifest_digest,args.expected_oci_digest,args.expected_harness,
            args.expected_source_revision,args.expected_realization_digest,
            args.expected_python_abi,
        ]
        if not all(expectations):
            parser.error("embedded portability requires manifest, source, harness, realization and ABI expectations")
        try:
            checked=verify_embedded(args.root,args.manifest_digest,args.expected_oci_digest,
                                    args.expected_harness,args.expected_source_revision,
                                    args.expected_realization_digest,args.expected_python_abi)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"PORTABILITY_VERIFIED {args.expected_harness}: {checked} files; no BUILD_ADMITTED or task claim")
        return 0
    admission=json.loads(args.admission.read_text(encoding="utf-8"))
    try:
        checked=verify(args.root,admission,args.manifest_digest)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"PASS {admission['harness']['name']} hydrated payload: {checked} files")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
