#!/usr/bin/env python3
import json
import sys
from pathlib import Path

b = json.loads(Path(sys.argv[1]).read_text())
assert b["probe_id"] == "cross-model-portability-tinyllama-v1"
assert b["model_identity"]["repository"] == "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
assert b["model_identity"]["revision"] == "fe8a4ea1ffedaf415f4da2f062534de366a451e6"
assert b["artifact_provenance"]["verified"] is True
assert len(b["observations"]["tasks"]) == 6
assert all(b["derived_metrics"]["portable_instrument_checks"].values())
assert 0 < float(b["cost"]["peak_rss_mib"]) < 15000
print(json.dumps({"validated": True, "run_id": b["provenance"]["run_id"], "manifest": b["artifact_provenance"]["identity_digest"], "peak_rss_mib": b["cost"]["peak_rss_mib"], "total_seconds": b["cost"]["total_seconds"]}, sort_keys=True))
