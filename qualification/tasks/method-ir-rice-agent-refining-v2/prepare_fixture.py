#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
FIXTURE=ROOT/"fixture"
MANIFEST=json.loads((FIXTURE/"source_manifest.json").read_text(encoding="utf-8"))
def main():
    observed={}
    for name,spec in MANIFEST["sources"].items():
        data=(FIXTURE/"sources"/name).read_bytes()
        if len(data)!=spec["size_bytes"] or hashlib.sha256(data).hexdigest()!=spec["sha256"]:
            raise SystemExit(f"{name}: frozen source mismatch")
        observed[name]={"sha256":spec["sha256"],"size_bytes":spec["size_bytes"]}
    print("PREPARED_RICE_V2_SOURCES="+json.dumps(observed,sort_keys=True))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
