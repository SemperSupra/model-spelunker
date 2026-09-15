#!/usr/bin/env python3
"""Rep 22: third-family portability on TinyLlama-1.1B-Chat-v1.0.

Reuse the already-qualified generic cross-model instrument stack unchanged while
substituting only exact model identity and local hydration location. The wrapper
exists to keep this rep a model substitution test rather than another harness
refactor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import run_cross_model_portability as portable

MODEL_REPO = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
MODEL_REVISION = "fe8a4ea1ffedaf415f4da2f062534de366a451e6"
LOGICAL_ID = "llm/tinyllama/1.1b-chat-v1.0"
LOCAL_DIR = "/tmp/model-spelunker-tinyllama-1.1b"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/tinyllama-portability.json"))
    args = parser.parse_args()

    portable.MODEL_REPO = MODEL_REPO
    portable.MODEL_REVISION = MODEL_REVISION
    portable.LOGICAL_ID = LOGICAL_ID

    original_snapshot_download = portable.snapshot_download

    def redirected_snapshot_download(*a, **kw):
        kw["local_dir"] = LOCAL_DIR
        return original_snapshot_download(*a, **kw)

    portable.snapshot_download = redirected_snapshot_download

    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    original_argv = sys.argv
    try:
        sys.argv = ["run_cross_model_portability.py", "--output", str(tmp)]
        rc = portable.main()
    finally:
        sys.argv = original_argv
        portable.snapshot_download = original_snapshot_download

    if rc != 0:
        return int(rc)

    bundle = json.loads(tmp.read_text())
    bundle["probe_id"] = "cross-model-portability-tinyllama-v1"
    bundle["model_identity"] = {
        "repository": MODEL_REPO,
        "revision": MODEL_REVISION,
        "logical_id": LOGICAL_ID,
    }
    bundle["derived_metrics"]["portability_rep"] = {
        "family_ordinal": 3,
        "model_family": "llama",
        "model_parameter_class": "1.1B",
        "harness_reused": "run_cross_model_portability.py",
    }
    bundle["provenance"]["model_substitution_wrapper"] = "run_tinyllama_portability.py"
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    tmp.unlink(missing_ok=True)
    print(json.dumps({
        "output": str(args.output),
        "probe_id": bundle["probe_id"],
        "model": MODEL_REPO,
        "revision": MODEL_REVISION,
        "artifact_identity": bundle["artifact_provenance"]["identity_digest"],
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
        "total_seconds": bundle["cost"]["total_seconds"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
