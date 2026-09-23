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


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("root",type=Path)
    parser.add_argument("admission",type=Path)
    parser.add_argument("--manifest-digest")
    args=parser.parse_args()

    admission=json.loads(args.admission.read_text(encoding="utf-8"))
    if admission["admission"]["state"]!="BUILD_ADMITTED":
        raise SystemExit("artifact is not BUILD_ADMITTED")

    expected_manifest=admission["artifact"]["digest"]
    if args.manifest_digest and args.manifest_digest!=expected_manifest:
        raise SystemExit(
            f"manifest digest mismatch: {args.manifest_digest} != {expected_manifest}"
        )

    artifact_root=args.root/"artifact"
    build_receipt=artifact_root/"build-receipt.json"
    if not build_receipt.is_file():
        raise SystemExit("missing embedded build receipt")

    expected_build=admission["artifact"]["build_receipt_digest"]
    actual_build=sha256_file(build_receipt)
    if actual_build!=expected_build:
        raise SystemExit(f"build receipt digest mismatch: {actual_build} != {expected_build}")

    receipt=json.loads(build_receipt.read_text(encoding="utf-8"))
    if receipt["harness"]["name"]!=admission["harness"]["name"]:
        raise SystemExit("harness name mismatch")

    checked=0
    for row in receipt["payload"]["files"]:
        path=artifact_root/row["path"]
        if not path.is_file():
            raise SystemExit(f"missing payload file: {row['path']}")
        if path.stat().st_size!=row["bytes"]:
            raise SystemExit(f"payload size mismatch: {row['path']}")
        actual=sha256_file(path).removeprefix("sha256:")
        if actual!=row["sha256"]:
            raise SystemExit(f"payload digest mismatch: {row['path']}")
        checked+=1

    if checked==0:
        raise SystemExit("embedded build receipt has no payload files")
    print(f"PASS {admission['harness']['name']} hydrated payload: {checked} files")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
