#!/usr/bin/env python3
"""Rep 25: cross-family attention-sink token-identity panel on Qwen2.5-0.5B.

This is intentionally a thin adapter over the Rep-18 generic sink-panel
instrument. It changes only model identity, the already-localized Qwen sink
head, and the frozen holdout corpus; the measurement/scoring machinery remains
shared.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import run_cross_model_portability as portable
import run_rep as base
import run_sink_token_panel as panel

QWEN_REPO = "Qwen/Qwen2.5-0.5B-Instruct"
QWEN_REVISION = "ec7ddfa904d4d447eedd0b7f126df16957734abb"
QWEN_LOGICAL_ID = "llm/qwen2.5/0.5b-instruct"

NEW_HOLDOUT = [
    {"task_id": "qhold-mul-7x8", "user": "Compute 7 x 8.", "correct": "56", "candidates": ["48", "54", "56", "63", "64"]},
    {"task_id": "qhold-sub-45-19", "user": "Compute 45 - 19.", "correct": "26", "candidates": ["24", "25", "26", "27", "28"]},
    {"task_id": "qhold-add-12-17", "user": "Compute 12 + 17.", "correct": "29", "candidates": ["27", "28", "29", "30", "31"]},
    {"task_id": "qhold-capital-france", "user": "What is the capital of France?", "correct": "Paris", "candidates": ["Paris", "Lyon", "Rome", "Madrid", "Berlin"]},
    {"task_id": "qhold-largest-ocean", "user": "Which is the largest ocean on Earth?", "correct": "Pacific", "candidates": ["Pacific", "Atlantic", "Indian", "Arctic", "Southern"]},
    {"task_id": "qhold-month-after-september", "user": "Which month comes immediately after September?", "correct": "October", "candidates": ["August", "October", "November", "December", "January"]},
    {"task_id": "qhold-decimal-larger", "user": "Which number is larger, 0.63 or 0.58?", "correct": "0.63", "candidates": ["0.53", "0.58", "0.60", "0.63", "0.68"]},
    {"task_id": "qhold-days-week", "user": "How many days are in a week?", "correct": "7", "candidates": ["5", "6", "7", "8", "9"]},
]

# Rebind model/artifact identity. The shared sink-panel instrument uses the
# standard base object, while the generic Rep-20 manifest implementation is
# reused because it correctly handles a model-family file set discovered by
# glob rather than SmolLM's explicit required-filename list.
base.MODEL_REPO = QWEN_REPO
base.MODEL_REVISION = QWEN_REVISION
base.LOGICAL_ID = QWEN_LOGICAL_ID
base.MODEL_FILES = ["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"]
portable.MODEL_REPO = QWEN_REPO
portable.MODEL_REVISION = QWEN_REVISION
portable.LOGICAL_ID = QWEN_LOGICAL_ID
base.content_manifest = portable.content_manifest

# Rep 20 independently localized a near-saturated Qwen first-token sink here.
panel.ATTENTION_LAYER = 11
panel.ATTENTION_HEAD = 13
panel.HOLDOUT = NEW_HOLDOUT

# Keep the generic panel implementation but make its ephemeral hydration path
# accurately named for this model family.
_original_snapshot_download = panel.snapshot_download

def _qwen_snapshot_download(*args, **kwargs):
    kwargs["local_dir"] = "/tmp/model-spelunker-qwen2.5-0.5b"
    return _original_snapshot_download(*args, **kwargs)

panel.snapshot_download = _qwen_snapshot_download


def _offset_prefix_region(tokenizer: Any, user: str, prompt: str) -> list[int]:
    """Return token positions strictly before user content using character offsets.

    Tokenizing `user` in isolation is not a portable alignment strategy: BPE
    tokenization may change at whitespace/prefix boundaries. Fast-tokenizer
    offset mappings instead align the actual full-prompt tokenization back to
    the exact user-character span. Added special tokens with zero-width offsets
    are naturally included when they occur before the first overlapping user
    token because the returned region is `range(first_user_token)`.
    """
    if not getattr(tokenizer, "is_fast", False):
        raise RuntimeError("offset-based prefix localization requires a fast tokenizer")
    char_start = prompt.find(user)
    if char_start < 0:
        raise RuntimeError("user text not found in rendered prompt")
    char_end = char_start + len(user)
    encoded = tokenizer(prompt, add_special_tokens=True, return_offsets_mapping=True)
    offsets = encoded["offset_mapping"]
    user_positions: list[int] = []
    for i, pair in enumerate(offsets):
        start, end = int(pair[0]), int(pair[1])
        if end <= start:
            continue
        if end > char_start and start < char_end:
            user_positions.append(i)
    if not user_positions:
        raise RuntimeError(
            f"no full-prompt token overlaps user character span {char_start}:{char_end}"
        )
    first_user_token = min(user_positions)
    return list(range(first_user_token))

# Evidence-earned portability correction: use the actual full-prompt token
# offsets rather than requiring an isolated user tokenization subsequence.
panel.prefix_region = _offset_prefix_region


def _output_path(argv: list[str]) -> Path:
    if "--output" in argv:
        i = argv.index("--output")
        return Path(argv[i + 1])
    return Path("out/sink-token-panel.json")


def main() -> int:
    output = _output_path(sys.argv)
    rc = panel.main()
    if rc != 0:
        return rc

    bundle = json.loads(output.read_text(encoding="utf-8"))
    bundle["probe_id"] = "qwen-sink-token-identity-panel-v1"
    bundle["instrument_version"] = "mvp-2-cross-family"
    bundle["uncertainty"] = {
        "status": "cross-family-predictive-screen",
        "notes": [
            "Calibration tasks and the token panel are reused as an instrument; all eight Qwen holdout tasks were fixed in code before this run.",
            "This tests transfer of the sink-token-identity phenomenon across model families, not promotion of any token as a capability recipe."
        ],
    }
    bundle["known_assumptions"] = [
        "Eligible panel strings that tokenize to one token are comparable under the common one-token-plus-newline layout.",
        "Qwen L11H13 prefix attention is used only as the independently localized sink-engagement sanity check, not as a capability metric.",
        "Prefix/user region alignment uses fast-tokenizer full-prompt character offsets rather than isolated-substring token IDs."
    ]

    for split in ("calibration_tasks", "holdout_tasks"):
        for task in bundle["observations"][split]:
            for row in task["conditions"].values():
                if "l18h8_prefix_attention_mass" in row:
                    row["attention_sink_prefix_mass"] = row.pop("l18h8_prefix_attention_mass")

    obs = bundle["observations"]
    bundle["provenance"]["raw_output_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(obs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "adapted_probe_id": bundle["probe_id"],
        "model": bundle["model_identity"],
        "attention_sanity_head": bundle["derived_metrics"]["attention_sanity_head"],
        "frozen_top3": bundle["derived_metrics"]["frozen_calibration_top3"],
        "rank_correlation": bundle["derived_metrics"]["calibration_holdout_rank_correlation"],
        "margin_correlation": bundle["derived_metrics"]["calibration_holdout_margin_correlation"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
