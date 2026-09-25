#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixture"
MANIFEST = json.loads((FIXTURE / "source_manifest.json").read_text(encoding="utf-8"))
REPO = MANIFEST["source_repository"]
COMMIT = MANIFEST["source_commit"]


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def main() -> int:
    for row in MANIFEST["files"]:
        rel = row["path"]
        url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{rel}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        actual = git_blob_sha(data)
        if actual != row["git_blob_sha"]:
            raise RuntimeError(
                f"source drift for {rel}: expected {row['git_blob_sha']} got {actual}"
            )
        target = FIXTURE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"PREPARED {rel} bytes={len(data)} git_blob={actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
