#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "tensorblock/llm4decompile-1.3b-v1.5-GGUF"
TARGET_SUFFIX = "Q4_K_M.gguf"
OUT = Path(os.environ.get("METADATA_OUT", "resolved-metadata.json"))

url = "https://huggingface.co/api/models/" + urllib.parse.quote(REPO, safe="/") + "?blobs=true"
with urllib.request.urlopen(url, timeout=60) as response:
    payload = json.load(response)

siblings = payload.get("siblings") or []
matches = [
    item for item in siblings
    if str(item.get("rfilename") or "").endswith(TARGET_SUFFIX)
]
if len(matches) != 1:
    names = [item.get("rfilename") for item in siblings]
    raise SystemExit(
        f"expected one *{TARGET_SUFFIX}, found {len(matches)}; repository files={names}"
    )
match = matches[0]
target = str(match["rfilename"])

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
    "file": target,
    "sha256": sha256,
    "size_bytes": int(size),
    "blob_id": match.get("blobId"),
    "license": (payload.get("cardData") or {}).get("license"),
    "pipeline_tag": payload.get("pipeline_tag"),
}
OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(record, sort_keys=True))
