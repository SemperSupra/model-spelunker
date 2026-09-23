#!/usr/bin/env python3
import hashlib
import json
import tempfile
from pathlib import Path

from verify_hydrated_artifact import verify


def digest(data: bytes) -> str:
    return "sha256:"+hashlib.sha256(data).hexdigest()


def make_case(root: Path, receipt: dict, target: str):
    artifact=root/"artifact"
    payload=artifact/"wheelhouse"/"openworker.whl"
    payload.parent.mkdir(parents=True,exist_ok=True)
    payload.write_bytes(b"wheel-payload\n")
    row={
        "path":"wheelhouse/openworker.whl",
        "bytes":payload.stat().st_size,
        "sha256":hashlib.sha256(payload.read_bytes()).hexdigest(),
    }
    receipt=json.loads(json.dumps(receipt))
    receipt.setdefault("payload",{})["files"]=[row]
    build=artifact/"build-receipt.json"
    build.write_text(json.dumps(receipt,sort_keys=True)+"\n",encoding="utf-8")
    admission={
        "harness":{"name":"openworker"},
        "artifact":{
            "digest":"sha256:"+"a"*64,
            "build_receipt_digest":digest(build.read_bytes()),
        },
        "admission":{"state":"BUILD_ADMITTED","target":target},
    }
    return admission


with tempfile.TemporaryDirectory(prefix="hydrated-verify-test-") as tmp:
    root=Path(tmp)/"linux"
    admission=make_case(root,{"harness":{"name":"openworker"}},"linux-x64")
    assert verify(root,admission)==1

    root=Path(tmp)/"mac"
    admission=make_case(
        root,
        {
            "source":{"repository":"https://github.com/andrewyng/openworker","revision":"abc"},
            "build":{"target":"macos-arm64-python3"},
        },
        "macos-arm64-python3",
    )
    assert verify(root,admission)==1

    bad=json.loads(json.dumps(admission))
    bad["admission"]["target"]="wrong-target"
    try:
        verify(root,bad)
    except ValueError as exc:
        assert "build target mismatch" in str(exc)
    else:
        raise AssertionError("mismatched target did not fail closed")

print("PASS hydrated artifact verifier supports explicit and digest-bound receipt shapes")
