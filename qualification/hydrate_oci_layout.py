#!/usr/bin/env python3
"""Hydrate a minimal OCI image layout without a container daemon.

The qualification artifacts are FROM scratch distribution envelopes. This
extractor intentionally supports regular files/directories and OCI whiteouts,
and rejects links/devices/path traversal instead of trying to be a general
container runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return "sha256:"+h.hexdigest()


def blob_path(layout: Path, digest: str) -> Path:
    algo, value=digest.split(":",1)
    if algo!="sha256" or len(value)!=64:
        raise ValueError(f"unsupported OCI digest: {digest}")
    path=layout/"blobs"/algo/value
    if not path.is_file():
        raise ValueError(f"missing OCI blob: {digest}")
    if sha256_file(path)!=digest:
        raise ValueError(f"OCI blob digest mismatch: {digest}")
    return path


def choose_manifest(layout: Path, ref_name: str | None) -> tuple[str, dict[str, Any]]:
    index=json.loads((layout/"index.json").read_text(encoding="utf-8"))
    manifests=index.get("manifests") or []
    if ref_name is not None:
        manifests=[
            item for item in manifests
            if (item.get("annotations") or {}).get("org.opencontainers.image.ref.name")==ref_name
        ]
    if len(manifests)!=1:
        raise ValueError(f"expected exactly one OCI manifest, found {len(manifests)}")
    descriptor=manifests[0]
    digest=descriptor["digest"]
    manifest=json.loads(blob_path(layout,digest).read_text(encoding="utf-8"))
    return digest,manifest


def safe_target(root: Path, name: str) -> Path:
    pure=PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe OCI layer path: {name}")
    target=(root/Path(*pure.parts)).resolve()
    root_resolved=root.resolve()
    if target!=root_resolved and root_resolved not in target.parents:
        raise ValueError(f"OCI layer path escapes root: {name}")
    return target


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def apply_layer(layer: Path, root: Path) -> None:
    with tarfile.open(layer, mode="r:*") as archive:
        for member in archive:
            pure=PurePosixPath(member.name)
            if not pure.parts:
                continue
            basename=pure.name
            parent_name=str(pure.parent) if str(pure.parent)!="." else ""
            parent=safe_target(root,parent_name)
            if basename==".wh..wh..opq":
                if parent.exists():
                    for child in parent.iterdir():
                        remove_path(child)
                continue
            if basename.startswith(".wh."):
                remove_path(parent/basename[4:])
                continue

            target=safe_target(root,member.name)
            if member.isdir():
                target.mkdir(parents=True,exist_ok=True)
                target.chmod(member.mode & 0o777)
                continue
            if member.isfile():
                target.parent.mkdir(parents=True,exist_ok=True)
                source=archive.extractfile(member)
                if source is None:
                    raise ValueError(f"missing file payload: {member.name}")
                with target.open("wb") as out:
                    shutil.copyfileobj(source,out)
                target.chmod(member.mode & 0o777)
                continue
            raise ValueError(f"unsupported OCI layer entry type: {member.name}")


def hydrate(layout: Path, output: Path, ref_name: str | None=None) -> dict[str, Any]:
    manifest_digest,manifest=choose_manifest(layout,ref_name)
    output.mkdir(parents=True,exist_ok=True)
    applied=[]
    for descriptor in manifest.get("layers") or []:
        digest=descriptor["digest"]
        layer=blob_path(layout,digest)
        apply_layer(layer,output)
        applied.append(digest)
    return {
        "schema_version":1,
        "manifest_digest":manifest_digest,
        "layers":applied,
        "output":str(output),
    }


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("layout",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--ref-name")
    parser.add_argument("--summary",type=Path)
    args=parser.parse_args()
    result=hydrate(args.layout,args.output,args.ref_name)
    payload=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if args.summary:
        args.summary.parent.mkdir(parents=True,exist_ok=True)
        args.summary.write_text(payload,encoding="utf-8")
    else:
        print(payload,end="")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
