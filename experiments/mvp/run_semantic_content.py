#!/usr/bin/env python3
"""Score semantic answer strings directly, removing A/B label priors."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import run_protocol_localization as loc
import run_rep as base

SPEC = Path("experiments/mvp/semantic-content-spec.json")
EXPANDED = Path("/tmp/model-spelunker-semantic-content.json")


def expand_spec() -> Path:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    probes: list[dict[str, Any]] = []
    for task in spec["tasks"]:
        probes.append({
            "probe_id": task["task_id"],
            "contrast_id": "user-wrapper-vs-no-user-wrapper",
            "expected_candidate": task["correct"],
            "candidates": [task["correct"], task["wrong"]],
            "conditions": [
                {"condition_id": "user-wrapper", "render": "no_system_cue", "user": task["user"]},
                {"condition_id": "no-user-wrapper", "render": "no_user_wrapper_cue", "user": task["user"]},
            ],
        })
    corpus = {
        "schema_version": spec["schema_version"],
        "corpus_id": spec["corpus_id"],
        "probes": probes,
    }
    EXPANDED.write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return EXPANDED


base.render_prompt = loc.render_prompt

if __name__ == "__main__":
    if "--probes" not in sys.argv:
        sys.argv.extend(["--probes", str(expand_spec())])
    raise SystemExit(base.main())
