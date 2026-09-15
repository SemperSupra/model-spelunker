#!/usr/bin/env python3
"""2x2 user-wrapper component localization on arithmetic rank surfaces."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import run_candidate_neighborhood as neighborhood
import run_rep as base

SPEC = Path("experiments/mvp/arithmetic-wrapper-factorial-spec.json")
EXPANDED = Path("/tmp/model-spelunker-arithmetic-wrapper-factorial.json")
ANSWER_TAIL = "<|im_start|>assistant\nAnswer: "

STATES = {
    "both": (True, True),
    "start-only": (True, False),
    "end-only": (False, True),
    "neither": (False, False),
}

CONTRASTS = [
    ("end-effect-start-present", "both", "start-only"),
    ("end-effect-start-absent", "end-only", "neither"),
    ("start-effect-end-present", "both", "end-only"),
    ("start-effect-end-absent", "start-only", "neither"),
]


def render_prompt(tokenizer: Any, condition: dict[str, Any]) -> str:
    del tokenizer
    user = condition["user"]
    try:
        start_present, end_present = STATES[condition["render"]]
    except KeyError as exc:
        raise ValueError(f"unsupported factorial render mode: {condition['render']}") from exc

    prefix = "<|im_start|>user\n" if start_present else ""
    suffix = "<|im_end|>\n" if end_present else "\n"
    return f"{prefix}{user}{suffix}{ANSWER_TAIL}"


def expand_spec() -> Path:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    probes: list[dict[str, Any]] = []
    for task in spec["tasks"]:
        for contrast_id, left_state, right_state in CONTRASTS:
            probes.append({
                "probe_id": f"{task['task_id']}-{contrast_id}",
                "contrast_id": contrast_id,
                "task_id": task["task_id"],
                "task_family": task["family"],
                "expected_candidate": task["correct"],
                "candidates": task["candidates"],
                "conditions": [
                    {"condition_id": left_state, "render": left_state, "user": task["user"]},
                    {"condition_id": right_state, "render": right_state, "user": task["user"]},
                ],
            })
    corpus = {
        "schema_version": spec["schema_version"],
        "corpus_id": spec["corpus_id"],
        "probes": probes,
    }
    EXPANDED.write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return EXPANDED


# Reuse the qualified candidate-neighborhood scoring implementation while
# substituting only the prompt renderer for this factorial experiment.
neighborhood.loc.render_prompt = render_prompt
base.run_condition = neighborhood.run_condition
base.render_prompt = render_prompt

if __name__ == "__main__":
    if "--probes" not in sys.argv:
        sys.argv.extend(["--probes", str(expand_spec())])
    raise SystemExit(base.main())
