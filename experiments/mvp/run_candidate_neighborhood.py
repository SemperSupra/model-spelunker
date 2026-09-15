#!/usr/bin/env python3
"""Rank broader semantic candidate neighborhoods using total and mean token log-probability."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import torch

import run_protocol_localization as loc
import run_rep as base

SPEC = Path("experiments/mvp/candidate-neighborhood-spec.json")
EXPANDED = Path("/tmp/model-spelunker-candidate-neighborhood.json")


def ranked(score_map: dict[str, float]) -> list[str]:
    return [k for k, _ in sorted(score_map.items(), key=lambda item: (-item[1], item[0]))]


def run_condition(
    model: Any,
    tokenizer: Any,
    condition: dict[str, Any],
    candidates: list[str],
    expected_candidate: str | None,
):
    started = base.now()
    prompt = loc.render_prompt(tokenizer, condition)
    encoded = tokenizer(prompt, return_tensors="pt")
    with torch.inference_mode():
        forward = model(**encoded, output_hidden_states=True, use_cache=False)
    hidden_summary, hidden_vectors = base.summarize_hidden(forward.hidden_states)

    scores = []
    for candidate in candidates:
        item = base.sequence_logprob(model, tokenizer, prompt, candidate)
        token_count = len(item["tokens"])
        if token_count <= 0:
            raise RuntimeError(f"candidate tokenized empty: {candidate!r}")
        item["token_count"] = token_count
        item["mean_logprob"] = float(item["logprob"] / token_count)
        scores.append(item)

    total_map = {x["candidate"]: float(x["logprob"]) for x in scores}
    mean_map = {x["candidate"]: float(x["mean_logprob"]) for x in scores}
    total_order = ranked(total_map)
    mean_order = ranked(mean_map)
    winner = mean_order[0]

    ordered_mean = sorted(mean_map.values(), reverse=True)
    top_margin = ordered_mean[0] - ordered_mean[1] if len(ordered_mean) > 1 else None
    expected_margin = None
    expected_rank_mean = None
    expected_rank_total = None
    if expected_candidate in mean_map:
        alternatives = [score for label, score in mean_map.items() if label != expected_candidate]
        expected_margin = mean_map[expected_candidate] - max(alternatives) if alternatives else None
        expected_rank_mean = mean_order.index(expected_candidate) + 1
        expected_rank_total = total_order.index(expected_candidate) + 1

    with torch.inference_mode():
        generated = model.generate(
            **encoded,
            max_new_tokens=16,
            do_sample=False,
            use_cache=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    new_ids = generated[0, encoded.input_ids.shape[1]:]
    generation = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
    generation_candidate = generation if generation in mean_map else None

    return ({
        "condition_id": condition["condition_id"],
        "render": condition["render"],
        "rendered_prompt": prompt,
        "prompt_sha256": "sha256:" + __import__("hashlib").sha256(prompt.encode("utf-8")).hexdigest(),
        "input_token_ids_sha256": base.token_hash(encoded.input_ids),
        "input_tokens": int(encoded.input_ids.numel()),
        "candidate_scores": scores,
        "candidate_score_metric": "mean_logprob",
        "candidate_winner": winner,
        "candidate_winner_total_logprob": total_order[0],
        "candidate_top_margin": top_margin,
        "candidate_correct": winner == expected_candidate if expected_candidate else None,
        "expected_candidate_margin": expected_margin,
        "expected_candidate_rank_mean": expected_rank_mean,
        "expected_candidate_rank_total": expected_rank_total,
        "generation": generation,
        "generation_candidate": generation_candidate,
        "generation_correct": generation_candidate == expected_candidate if generation_candidate and expected_candidate else None,
        "surface_generation_agree": generation_candidate == winner if generation_candidate else None,
        "hidden_summary": hidden_summary,
        "elapsed_seconds": base.now() - started,
    }, hidden_vectors)


def expand_spec() -> Path:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    probes: list[dict[str, Any]] = []
    for task in spec["tasks"]:
        probes.append({
            "probe_id": task["task_id"],
            "contrast_id": "user-wrapper-vs-no-user-wrapper",
            "expected_candidate": task["correct"],
            "candidates": task["candidates"],
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
base.run_condition = run_condition

if __name__ == "__main__":
    if "--probes" not in sys.argv:
        sys.argv.extend(["--probes", str(expand_spec())])
    raise SystemExit(base.main())
