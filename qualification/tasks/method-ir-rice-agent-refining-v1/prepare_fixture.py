#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixture"
MANIFEST = json.loads((FIXTURE / "source_manifest.json").read_text(encoding="utf-8"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    observed = {}
    for name, spec in MANIFEST["sources"].items():
        path = FIXTURE / "sources" / name
        data = path.read_bytes()
        if len(data) != spec["size_bytes"]:
            raise SystemExit(f"{name}: size mismatch")
        if sha256(data) != spec["sha256"]:
            raise SystemExit(f"{name}: sha256 mismatch")
        observed[name] = {"sha256": spec["sha256"], "size_bytes": spec["size_bytes"]}
    print("PREPARED_RICE_SOURCES=" + json.dumps(observed, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
