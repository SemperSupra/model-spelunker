#!/usr/bin/env python3
"""Thin rendering adapter for the protocol-localization rep.

Keeps the common Model Spelunker evidence engine unchanged while forcing all
conditions to terminate at the same literal `Answer: ` cue. Synthetic ablations
remove one protocol component at a time; they are system-identification probes,
not recommended production prompt formats.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import run_rep as base

ANSWER_CUE = "Answer: "
SPEC = Path("experiments/mvp/protocol-localization-spec.json")
EXPANDED = Path("/tmp/model-spelunker-protocol-localization.json")

CONTRASTS = [
    (
        "full-vs-no-system",
        ("native-cue", "native_cue"),
        ("no-system-cue", "no_system_cue"),
    ),
    (
        "no-system-vs-no-user-wrapper",
        ("no-system-cue", "no_system_cue"),
        ("no-user-wrapper-cue", "no_user_wrapper_cue"),
    ),
    (
        "no-user-wrapper-vs-raw",
        ("no-user-wrapper-cue", "no_user_wrapper_cue"),
        ("raw-cue", "raw_cue"),
    ),
]


def render_prompt(tokenizer: Any, condition: dict[str, Any]) -> str:
    user = condition["user"]
    mode = condition["render"]

    if mode == "native_cue":
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": user}],
            tokenize=False,
            add_generation_prompt=True,
        )
        return prompt + ANSWER_CUE

    if mode == "no_system_cue":
        return (
            f"<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n{ANSWER_CUE}"
        )

    if mode == "no_user_wrapper_cue":
        return f"{user}\n<|im_start|>assistant\n{ANSWER_CUE}"

    if mode == "raw_cue":
        return f"{user}\n{ANSWER_CUE}"

    raise ValueError(f"unsupported protocol-localization render mode: {mode}")


def expand_spec() -> Path:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    probes: list[dict[str, Any]] = []
    for task in spec["tasks"]:
        for contrast_id, left, right in CONTRASTS:
            probes.append({
                "probe_id": f"{task['task_id']}-{contrast_id}",
                "contrast_id": contrast_id,
                "expected_candidate": task["expected_candidate"],
                "candidates": ["A", "B"],
                "conditions": [
                    {"condition_id": left[0], "render": left[1], "user": task["user"]},
                    {"condition_id": right[0], "render": right[1], "user": task["user"]},
                ],
            })
    corpus = {
        "schema_version": spec["schema_version"],
        "corpus_id": spec["corpus_id"],
        "probes": probes,
    }
    EXPANDED.write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return EXPANDED


base.render_prompt = render_prompt

if __name__ == "__main__":
    if "--probes" not in sys.argv:
        sys.argv.extend(["--probes", str(expand_spec())])
    raise SystemExit(base.main())
