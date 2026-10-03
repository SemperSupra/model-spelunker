#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

MAX_AGENT_DISPATCH_B64 = 60_000


def build(study_dir: Path, out_dir: Path) -> dict[str, object]:
    required = ["run.sh", "run_reproduction.py", "study.json"]
    for name in required:
        if not (study_dir / name).is_file():
            raise SystemExit(f"missing required capsule file: {study_dir / name}")

    out_dir.mkdir(parents=True, exist_ok=True)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz", compresslevel=9) as tf:
        for name in required:
            path = study_dir / name
            info = tf.gettarinfo(str(path), arcname=name)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            with path.open("rb") as fh:
                tf.addfile(info, fh)

    capsule = raw.getvalue()
    encoded = base64.b64encode(capsule).decode("ascii")
    if len(encoded) > MAX_AGENT_DISPATCH_B64:
        raise SystemExit(
            f"capsule base64 is {len(encoded)} chars; Agent Dispatch maximum is {MAX_AGENT_DISPATCH_B64}"
        )

    sha = hashlib.sha256(capsule).hexdigest()
    (out_dir / "capsule.tar.gz").write_bytes(capsule)
    (out_dir / "capsule.b64").write_text(encoded + "\n", encoding="ascii")
    manifest = {
        "schema_version": 1,
        "study_dir": study_dir.as_posix(),
        "capsule_sha256": sha,
        "capsule_bytes": len(capsule),
        "capsule_b64_chars": len(encoded),
        "agent_dispatch_contract": "SemperSupra/agent-dispatch:.github/workflows/sealed-public-execution.yml",
        "files": {
            name: {
                "sha256": hashlib.sha256((study_dir / name).read_bytes()).hexdigest(),
                "bytes": (study_dir / name).stat().st_size,
            }
            for name in required
        },
    }
    (out_dir / "capsule-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("study_dir", type=Path)
    parser.add_argument("--out", type=Path, default=Path(".capsule"))
    args = parser.parse_args()
    manifest = build(args.study_dir, args.out)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
