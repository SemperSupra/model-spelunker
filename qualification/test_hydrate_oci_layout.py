#!/usr/bin/env python3
import hashlib
import io
import json
import tarfile
import tempfile
from pathlib import Path

from qualification.hydrate_oci_layout import hydrate


def sha(data: bytes) -> str:
    return "sha256:"+hashlib.sha256(data).hexdigest()


def add_blob(layout: Path, data: bytes) -> str:
    digest=sha(data)
    algo,value=digest.split(":",1)
    path=layout/"blobs"/algo/value
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)
    return digest


def layer(entries):
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode="w") as tf:
        for name,data,mode in entries:
            info=tarfile.TarInfo(name)
            info.mode=mode
            info.size=len(data)
            tf.addfile(info,io.BytesIO(data))
    return buf.getvalue()


with tempfile.TemporaryDirectory(prefix="oci-layout-test-") as tmp:
    root=Path(tmp)
    layout=root/"layout"
    out=root/"out"
    (layout/"blobs"/"sha256").mkdir(parents=True)
    (layout/"oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}\n')

    l1=layer([
        ("artifact/build-receipt.json",b"{}\n",0o644),
        ("artifact/tool",b"v1\n",0o755),
        ("artifact/obsolete",b"old\n",0o644),
    ])
    l2=layer([
        ("artifact/.wh.obsolete",b"",0o000),
        ("artifact/tool",b"v2\n",0o755),
    ])
    d1=add_blob(layout,l1)
    d2=add_blob(layout,l2)
    config=add_blob(layout,b"{}")
    manifest_obj={
        "schemaVersion":2,
        "config":{"mediaType":"application/vnd.oci.image.config.v1+json","digest":config,"size":2},
        "layers":[
            {"mediaType":"application/vnd.oci.image.layer.v1.tar","digest":d1,"size":len(l1)},
            {"mediaType":"application/vnd.oci.image.layer.v1.tar","digest":d2,"size":len(l2)},
        ],
    }
    manifest_bytes=json.dumps(manifest_obj,sort_keys=True,separators=(",",":")).encode()
    manifest=add_blob(layout,manifest_bytes)
    index={
        "schemaVersion":2,
        "manifests":[{
            "mediaType":"application/vnd.oci.image.manifest.v1+json",
            "digest":manifest,
            "size":len(manifest_bytes),
            "annotations":{"org.opencontainers.image.ref.name":"artifact"},
        }],
    }
    (layout/"index.json").write_text(json.dumps(index))

    result=hydrate(layout,out,"artifact")
    assert result["manifest_digest"]==manifest
    assert (out/"artifact/tool").read_text()=="v2\n"
    assert not (out/"artifact/obsolete").exists()
    assert (out/"artifact/tool").stat().st_mode & 0o111

    bad=layer([("../escape",b"bad",0o644)])
    bad_digest=add_blob(layout,bad)
    manifest_obj["layers"]=[{"mediaType":"application/vnd.oci.image.layer.v1.tar","digest":bad_digest,"size":len(bad)}]
    mb=json.dumps(manifest_obj,sort_keys=True,separators=(",",":")).encode()
    md=add_blob(layout,mb)
    index["manifests"][0]["digest"]=md
    index["manifests"][0]["size"]=len(mb)
    (layout/"index.json").write_text(json.dumps(index))
    try:
        hydrate(layout,root/"bad-out","artifact")
    except ValueError as exc:
        assert "unsafe OCI layer path" in str(exc)
    else:
        raise AssertionError("path traversal layer did not fail closed")

print("PASS daemonless OCI hydration and traversal rejection")
