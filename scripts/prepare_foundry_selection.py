#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def content_manifest_material(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "logical_id": candidate["logical_id"],
        "upstream": {
            "provider": candidate["upstream"]["provider"],
            "repository": candidate["upstream"]["repository"],
            "exact_revision": candidate["upstream"]["exact_revision"],
        },
        "files": sorted(candidate["files"], key=lambda item: item["path"]),
    }


def content_manifest_digest(material: dict[str, Any]) -> str:
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def verify_content_manifest(candidate: dict[str, Any], model_dir: Path, foundry_ref: str) -> dict[str, Any]:
    identity = candidate.get("artifact_identity") or {}
    if identity.get("kind") != "content-manifest":
        raise RuntimeError("this MVP verifier currently accepts only Foundry content-manifest candidates")
    if candidate.get("state") != "candidate":
        raise RuntimeError("expected a Foundry candidate record")
    if not foundry_ref or ":" not in foundry_ref or "@" not in foundry_ref:
        raise RuntimeError("foundry_ref must bind repository, immutable commit, and evidence path")

    files = sorted(candidate.get("files") or [], key=lambda item: item.get("path", ""))
    if not files:
        raise RuntimeError("candidate contains no file manifest")
    expected_names = [entry["path"] for entry in files]
    if len(expected_names) != len(set(expected_names)):
        raise RuntimeError("candidate contains duplicate file paths")

    actual_names = sorted(
        path.relative_to(model_dir).as_posix()
        for path in model_dir.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    if actual_names != expected_names:
        raise RuntimeError(f"hydrated file set mismatch: expected={expected_names}, actual={actual_names}")

    for entry in files:
        path = model_dir / entry["path"]
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"hydrated member is not a regular file: {entry['path']}")
        if path.stat().st_size != int(entry["size_bytes"]):
            raise RuntimeError(f"hydrated size mismatch: {entry['path']}")
        if sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"hydrated SHA-256 mismatch: {entry['path']}")

    material = content_manifest_material(candidate)
    digest = content_manifest_digest(material)
    if digest != identity.get("digest"):
        raise RuntimeError(
            f"Foundry content-manifest digest mismatch: expected={identity.get('digest')} recomputed={digest}"
        )

    return {
        "logical_id": candidate["logical_id"],
        "upstream_repository": candidate["upstream"]["repository"],
        "upstream_exact_revision": candidate["upstream"]["exact_revision"],
        "identity_kind": "content-manifest",
        "identity_digest": digest,
        "foundry_ref": foundry_ref,
        "hydration_verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--foundry-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    selection = verify_content_manifest(candidate, args.model_dir, args.foundry_ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(selection, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
