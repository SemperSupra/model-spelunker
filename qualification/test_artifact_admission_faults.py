#!/usr/bin/env python3
import hashlib
import json
import tempfile
from copy import deepcopy
from pathlib import Path

from qualification.verify_hydrated_artifact import verify


def h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


with tempfile.TemporaryDirectory(prefix="artifact-faults-") as tmp:
    root=Path(tmp)
    artifact=root/"artifact"
    artifact.mkdir(parents=True)
    payload=b"payload\n"
    (artifact/"tool").write_bytes(payload)
    receipt={
        "schema_version":1,
        "record_type":"harness-build-receipt",
        "harness":{"name":"fixture","declared_version":"1"},
        "source":{"repository":"fixture","revision":"abcdef0","lockfile_digest":None},
        "build":{"recipe_id":"fixture","target":"linux-x86_64","builder_class":"fixture","toolchain":"fixture","configuration":{}},
        "payload":{"kind":"native-binary","files":[{"path":"tool","sha256":h(payload),"bytes":len(payload)}]},
    }
    encoded=(json.dumps(receipt,indent=2,sort_keys=True)+"\n").encode()
    (artifact/"build-receipt.json").write_bytes(encoded)
    build_digest="sha256:"+h(encoded)
    manifest="sha256:"+"1"*64
    admission={
        "schema_version":1,
        "record_type":"harness-artifact-admission",
        "harness":{"name":"fixture","declared_version":"1"},
        "artifact":{
            "packaging":"oci-distribution",
            "ref":"ghcr.io/example/fixture@"+manifest,
            "digest":manifest,
            "build_receipt_digest":build_digest,
        },
        "admission":{"state":"BUILD_ADMITTED","target":"linux-x86_64","checks":[{"name":"fixture","result":"PASS","evidence":None}]},
    }

    assert verify(root,admission,manifest)==1

    wrong_manifest=deepcopy(admission)
    try:
        verify(root,wrong_manifest,"sha256:"+"2"*64)
    except ValueError as exc:
        assert "manifest digest mismatch" in str(exc)
    else:
        raise AssertionError("wrong manifest digest did not fail closed")

    wrong_receipt=deepcopy(admission)
    wrong_receipt["artifact"]["build_receipt_digest"]="sha256:"+"3"*64
    try:
        verify(root,wrong_receipt,manifest)
    except ValueError as exc:
        assert "build receipt digest mismatch" in str(exc)
    else:
        raise AssertionError("mismatched admission receipt did not fail closed")

    original=(artifact/"tool").read_bytes()
    (artifact/"tool").write_bytes(original+b"tamper")
    try:
        verify(root,admission,manifest)
    except ValueError as exc:
        assert "payload size mismatch" in str(exc) or "payload digest mismatch" in str(exc)
    else:
        raise AssertionError("tampered payload did not fail closed")

print("PASS artifact admission fault injection")
