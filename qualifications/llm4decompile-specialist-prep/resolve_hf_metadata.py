#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "tensorblock/llm4decompile-1.3b-v1.5-GGUF"
TARGET = "llm4decompile-1.3b-v1.5-Q4_K_M.gguf"
OUT = Path(os.environ.get("METADATA_OUT", "resolved-metadata.json"))

url = "https://huggingface.co/api/models/" + urllib.parse.quote(REPO, safe="/") + "?blobs=true"
with urllib.request.urlopen(url, timeout=60) as response:
    payload = json.load(response)

siblings = payload.get("siblings") or []
match = next((item for item in siblings if item.get("rfilename") == TARGET), None)
if not match:
    raise SystemExit(f"target file not found: {TARGET}")

lfs = match.get("lfs") or {}
sha256 = lfs.get("sha256")
size = lfs.get("size") or match.get("size")
revision = payload.get("sha")

if not revision or not sha256 or not size:
    raise SystemExit(
        f"metadata incomplete: revision={revision!r} sha256={sha256!r} size={size!r}"
    )

record = {
    "schema_version": 1,
    "record_type": "hf-artifact-metadata",
    "repository": REPO,
    "revision": revision,
    "file": TARGET,
    "sha256": sha256,
    "size_bytes": int(size),
    "blob_id": match.get("blobId"),
    "license": (payload.get("cardData") or {}).get("license"),
    "pipeline_tag": payload.get("pipeline_tag"),
}
OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(record, sort_keys=True))
