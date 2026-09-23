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
    # Older/Linux build receipts carry an explicit harness identity. The accepted
    # macOS characterization receipt predates that field but is already bound by
    # the admission's exact build-receipt digest. Preserve the stronger explicit
    # check when present; otherwise require target consistency when available.
    receipt_harness=(receipt.get("harness") or {}).get("name")
    if receipt_harness is not None and receipt_harness!=admission["harness"]["name"]:
        raise ValueError("harness name mismatch")
    receipt_target=(receipt.get("build") or {}).get("target")
    admission_target=(admission.get("admission") or {}).get("target")
    if receipt_target is not None and admission_target is not None and receipt_target!=admission_target:
        raise ValueError(f"build target mismatch: {receipt_target} != {admission_target}")

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


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("root",type=Path)
    parser.add_argument("admission",type=Path)
    parser.add_argument("--manifest-digest")
    args=parser.parse_args()

    admission=json.loads(args.admission.read_text(encoding="utf-8"))
    try:
        checked=verify(args.root,admission,args.manifest_digest)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"PASS {admission['harness']['name']} hydrated payload: {checked} files")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
