#!/usr/bin/env python3
"""Create a deterministic OCI image layout for a harness distribution payload.

The input directory is projected beneath /artifact in a single uncompressed OCI
layer. This is packaging only: no container daemon/runtime is required or used.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import stat
import tarfile
from typing import Iterable

OCI_LAYOUT_VERSION = "1.0.0"
OCI_IMAGE_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_IMAGE_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER_TAR = "application/vnd.oci.image.layer.v1.tar"
OCI_REF_ANNOTATION = "org.opencontainers.image.ref.name"


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_blob(layout: Path, data: bytes) -> tuple[str, int]:
    digest = digest_bytes(data)
    algo, value = digest.split(":", 1)
    path = layout / "blobs" / algo / value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return digest, len(data)


def safe_relative_files(root: Path) -> Iterable[Path]:
    base = root.resolve()
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        resolved = path.resolve()
        if resolved != base and base not in resolved.parents:
            raise ValueError(f"path escapes payload root: {path}")
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed in harness OCI payloads: {path}")
        if path.is_file():
            yield path
        elif path.is_dir():
            continue
        else:
            raise ValueError(f"unsupported payload entry: {path}")


def normalized_mode(path: Path) -> int:
    mode = stat.S_IMODE(path.stat().st_mode)
    return 0o755 if (mode & 0o111) else 0o644


def build_layer(root: Path) -> bytes:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"payload root is not a directory: {root}")

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        # Explicit artifact root keeps the carrier shape stable.
        top = tarfile.TarInfo("artifact")
        top.type = tarfile.DIRTYPE
        top.mode = 0o755
        top.uid = top.gid = 0
        top.uname = top.gname = ""
        top.mtime = 0
        archive.addfile(top)

        emitted_dirs: set[str] = {"artifact"}
        for path in safe_relative_files(root):
            rel = path.relative_to(root).as_posix()
            parent_parts = rel.split("/")[:-1]
            current = "artifact"
            for part in parent_parts:
                current = current + "/" + part
                if current in emitted_dirs:
                    continue
                info = tarfile.TarInfo(current)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                archive.addfile(info)
                emitted_dirs.add(current)

            data = path.read_bytes()
            info = tarfile.TarInfo("artifact/" + rel)
            info.size = len(data)
            info.mode = normalized_mode(path)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def package(payload: Path, layout: Path, ref_name: str, architecture: str, os_name: str) -> dict:
    if layout.exists():
        if any(layout.iterdir()):
            raise ValueError(f"output OCI layout must be empty: {layout}")
    else:
        layout.mkdir(parents=True)

    layer = build_layer(payload)
    layer_digest, layer_size = write_blob(layout, layer)

    config = {
        "architecture": architecture,
        "os": os_name,
        "config": {},
        "rootfs": {
            "type": "layers",
            "diff_ids": [layer_digest],
        },
    }
    config_bytes = canonical_json_bytes(config)
    config_digest, config_size = write_blob(layout, config_bytes)

    manifest = {
        "schemaVersion": 2,
        "mediaType": OCI_IMAGE_MANIFEST,
        "config": {
            "mediaType": OCI_IMAGE_CONFIG,
            "digest": config_digest,
            "size": config_size,
        },
        "layers": [
            {
                "mediaType": OCI_LAYER_TAR,
                "digest": layer_digest,
                "size": layer_size,
            }
        ],
    }
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_digest, manifest_size = write_blob(layout, manifest_bytes)

    index = {
        "schemaVersion": 2,
        "manifests": [
            {
                "mediaType": OCI_IMAGE_MANIFEST,
                "digest": manifest_digest,
                "size": manifest_size,
                "platform": {
                    "architecture": architecture,
                    "os": os_name,
                },
                "annotations": {
                    OCI_REF_ANNOTATION: ref_name,
                },
            }
        ],
    }

    (layout / "oci-layout").write_text(
        json.dumps({"imageLayoutVersion": OCI_LAYOUT_VERSION}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (layout / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "schema_version": 1,
        "record_type": "harness-oci-layout-receipt",
        "ref_name": ref_name,
        "platform": {
            "architecture": architecture,
            "os": os_name,
        },
        "manifest_digest": manifest_digest,
        "config_digest": config_digest,
        "layer_digest": layer_digest,
        "layer_size_bytes": layer_size,
        "payload_root": "artifact",
        "container_runtime_used": False,
        "docker_socket_used": False,
        "sudo_used": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path)
    parser.add_argument("layout", type=Path)
    parser.add_argument("--ref-name", default="artifact")
    parser.add_argument("--architecture", default="amd64")
    parser.add_argument("--os", dest="os_name", default="linux")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()

    result = package(
        args.payload,
        args.layout,
        args.ref_name,
        args.architecture,
        args.os_name,
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
