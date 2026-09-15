#!/usr/bin/env python3
"""Thin rendering adapter for the protocol-localization rep.

Keeps the common Model Spelunker evidence engine unchanged while forcing all
conditions to terminate at the same literal `Answer: ` cue. Synthetic ablations
remove one protocol component at a time; they are system-identification probes,
not recommended production prompt formats.
"""
from __future__ import annotations

from typing import Any

import run_rep as base

ANSWER_CUE = "Answer: "


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


base.render_prompt = render_prompt

if __name__ == "__main__":
    raise SystemExit(base.main())
