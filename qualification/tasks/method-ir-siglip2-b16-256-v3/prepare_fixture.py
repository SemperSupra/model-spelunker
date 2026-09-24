#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixture"
MANIFEST = json.loads((FIXTURE / "source_manifest.json").read_text(encoding="utf-8"))
SOURCES = FIXTURE / "sources"
UA = "Model-Spelunker/1.0 (+https://github.com/SemperSupra/model-spelunker)"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def require_bytes(label: str, data: bytes, expected_sha: str, expected_size: int) -> None:
    if len(data) != expected_size:
        raise SystemExit(f"{label}: size mismatch: {len(data)} != {expected_size}")
    got = sha256(data)
    if got != expected_sha:
        raise SystemExit(f"{label}: sha256 mismatch: {got} != {expected_sha}")


def write_numbered(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    companion = path.with_name(path.name + ".lines.txt")
    companion.write_text(
        "".join(f"{i:05d}: {line}\n" for i, line in enumerate(lines, 1)),
        encoding="utf-8",
    )


def main() -> int:
    arxiv = MANIFEST["arxiv"]
    tar_bytes = fetch(arxiv["source_url"])
    require_bytes(
        "arxiv source tar",
        tar_bytes,
        arxiv["tar_sha256"],
        arxiv["tar_size_bytes"],
    )

    if SOURCES.exists():
        shutil.rmtree(SOURCES)
    (SOURCES / "tables").mkdir(parents=True)

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as archive:
        members = {member.name: member for member in archive.getmembers() if member.isfile()}
        for source_name, identity in arxiv["selected_files"].items():
            member = members.get(source_name)
            if member is None:
                raise SystemExit(f"missing frozen arxiv member: {source_name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise SystemExit(f"cannot read frozen arxiv member: {source_name}")
            data = extracted.read()
            require_bytes(source_name, data, identity["sha256"], identity["size_bytes"])
            target = SOURCES / source_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            write_numbered(target)

    readme = MANIFEST["checkpoint_readme"]
    readme_bytes = fetch(readme["raw_url"])
    require_bytes(
        "checkpoint README",
        readme_bytes,
        readme["sha256"],
        readme["size_bytes"],
    )
    readme_path = SOURCES / "README_siglip2.md"
    readme_path.write_bytes(readme_bytes)
    write_numbered(readme_path)

    prepared = {
        "schema_version": 1,
        "specimen_id": MANIFEST["specimen_id"],
        "sources": {
            "document.tex": arxiv["selected_files"]["document.tex"],
            "tables/zeroshot_main.tex": arxiv["selected_files"]["tables/zeroshot_main.tex"],
            "README_siglip2.md": {
                "sha256": readme["sha256"],
                "size_bytes": readme["size_bytes"],
            },
        },
    }
    (FIXTURE / "prepared_sources.json").write_text(
        json.dumps(prepared, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("PREPARED_SIGLIP2_SOURCES=" + json.dumps(prepared, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
