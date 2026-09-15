#!/usr/bin/env python3
"""Label-permutation falsification rep for the protocol control-surface signal."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import run_protocol_localization as loc
import run_rep as base

SPEC = Path("experiments/mvp/label-permutation-spec.json")
EXPANDED = Path("/tmp/model-spelunker-label-permutation.json")


def expand_spec() -> Path:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    probes: list[dict[str, Any]] = []
    for task in spec["tasks"]:
        labelings = [
            ("correct-is-a", task["correct"], task["wrong"], "A"),
            ("correct-is-b", task["wrong"], task["correct"], "B"),
        ]
        for labeling_id, option_a, option_b, expected in labelings:
            user = (
                f"{task['stem']} A) {option_a} B) {option_b}. "
                "Answer only A or B."
            )
            probes.append({
                "probe_id": f"{task['task_id']}-{labeling_id}",
                "contrast_id": labeling_id,
                "expected_candidate": expected,
                "candidates": ["A", "B"],
                "conditions": [
                    {"condition_id": "user-wrapper", "render": "no_system_cue", "user": user},
                    {"condition_id": "no-user-wrapper", "render": "no_user_wrapper_cue", "user": user},
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
