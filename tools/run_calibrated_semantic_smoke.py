#!/usr/bin/env python3
"""Label-free calibrated semantic scorer for Experiment 0001.

Scores complete positive/negative natural-language continuations and subtracts each
continuation's score under a language-matched neutral stem. This reduces raw answer
frequency/fluency priors without claiming the resulting delta is a mechanistic
concept measure.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch
from huggingface_hub import model_info
from jsonschema import Draft202012Validator
from transformers import AutoModelForCausalLM, AutoTokenizer

SCHEMA_VERSION = "0.1.0"
PROMPT_TEMPLATE_VERSION = "semantic-calibrated-v0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        default="fixtures/experiment-0001/reciprocity-semantic-smoke.jsonl",
    )
    parser.add_argument("--schema", default="schemas/concept-geometry-record.schema.json")
    parser.add_argument("--model", default="EleutherAI/pythia-70m")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--output-dir", default="artifacts/experiment-0001-semantic")
    parser.add_argument("--max-probes", type=int, default=0, help="0 means all probes")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def conditional_mean_logprob(
    model: AutoModelForCausalLM,
    tokenizer: AutoTokenizer,
    prompt: str,
    continuation: str,
) -> tuple[float, int]:
    prompt_ids = tokenizer(prompt, add_special_tokens=False, return_tensors="pt").input_ids
    full_ids = tokenizer(prompt + continuation, add_special_tokens=False, return_tensors="pt").input_ids

    prompt_len = prompt_ids.shape[1]
    full_len = full_ids.shape[1]
    if full_len <= prompt_len:
        raise ValueError(f"Continuation produced no additional tokens: {continuation!r}")

    # Fail closed if tokenization at the prompt/continuation boundary is not prefix-stable.
    # The fixtures deliberately use a leading space on continuations for this reason.
    if not torch.equal(full_ids[:, :prompt_len], prompt_ids):
        raise ValueError(
            "Prompt tokenization is not a prefix of prompt+continuation tokenization; "
            "change the fixture boundary instead of silently mis-scoring it."
        )

    with torch.inference_mode():
        logits = model(full_ids).logits
        log_probs = torch.log_softmax(logits, dim=-1)

    token_logps: list[float] = []
    for token_position in range(prompt_len, full_len):
        prediction_position = token_position - 1
        target_id = int(full_ids[0, token_position])
        token_logps.append(float(log_probs[0, prediction_position, target_id]))

    return sum(token_logps) / len(token_logps), len(token_logps)


def fragmentation_ratio(tokenizer: AutoTokenizer, text: str) -> float:
    token_count = len(tokenizer(text, add_special_tokens=False).input_ids)
    nonspace_chars = sum(1 for char in text if not char.isspace())
    return token_count / max(1, nonspace_chars)


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))

    fixture_path = Path(args.fixture)
    schema_path = Path(args.schema)
    output_dir = Path(args.output_dir)
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    probes = read_jsonl(fixture_path)
    rng.shuffle(probes)
    if args.max_probes > 0:
        probes = probes[: args.max_probes]

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(f"Could not resolve immutable revision for {args.model}@{args.revision}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=resolved_revision)
    model.eval()
    model.to("cpu")

    records_path = output_dir / "concept-geometry-records.jsonl"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "model": args.model,
        "requested_revision": args.revision,
        "resolved_revision": resolved_revision,
        "fixture": str(fixture_path),
        "seed": args.seed,
        "probe_count": len(probes),
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "calibration": "mean_logprob(prompt,candidate)-mean_logprob(neutral_prompt,candidate)",
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with records_path.open("w", encoding="utf-8") as records_file:
        for probe in probes:
            started = time.perf_counter()
            candidates = {
                "positive": probe["positive_continuation"],
                "negative": probe["negative_continuation"],
            }

            prompted: dict[str, float] = {}
            neutral: dict[str, float] = {}
            calibrated: dict[str, float] = {}
            token_counts: dict[str, int] = {}

            for name, continuation in candidates.items():
                prompted_score, candidate_tokens = conditional_mean_logprob(
                    model, tokenizer, probe["prompt"], continuation
                )
                neutral_score, neutral_candidate_tokens = conditional_mean_logprob(
                    model, tokenizer, probe["neutral_prompt"], continuation
                )
                if candidate_tokens != neutral_candidate_tokens:
                    raise ValueError(
                        f"Candidate token count changed under calibration stem for {probe['surface_id']}:{name}"
                    )
                prompted[name] = prompted_score
                neutral[name] = neutral_score
                calibrated[name] = prompted_score - neutral_score
                token_counts[name] = candidate_tokens

            selected = max(calibrated, key=calibrated.get)
            expected = probe.get("expected")
            machine_score = None if expected is None else float(selected == expected)
            elapsed_ms = (time.perf_counter() - started) * 1000.0

            raw_path = raw_dir / f"{probe['surface_id']}.json"
            raw_payload = {
                "surface_id": probe["surface_id"],
                "prompt": probe["prompt"],
                "neutral_prompt": probe["neutral_prompt"],
                "candidates": candidates,
                "expected": expected,
                "selected": selected,
                "prompted_mean_logprob": prompted,
                "neutral_mean_logprob": neutral,
                "calibrated_delta": calibrated,
                "candidate_token_counts": token_counts,
            }
            raw_path.write_text(
                json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            record = {
                "schema_version": SCHEMA_VERSION,
                "concept_id": probe["concept_id"],
                "concept_version": probe["concept_version"],
                "model": {
                    "artifact_id": args.model,
                    "revision": resolved_revision,
                    "tokenizer_revision": resolved_revision,
                    "artifact_digest": f"hf-commit:{resolved_revision}",
                },
                "probe": {
                    "probe_id": probe["probe_id"],
                    "surface_id": probe["surface_id"],
                    "class": probe["class"],
                    "language": probe["language"],
                    "formulation_type": probe["formulation_type"],
                    "source": probe["source"],
                    "translation_path": probe.get("translation_path"),
                },
                "run": {
                    "seed": args.seed,
                    "prompt_template_version": PROMPT_TEMPLATE_VERSION,
                    "input_tokens": len(
                        tokenizer(probe["prompt"], add_special_tokens=False).input_ids
                    ),
                    "output_tokens": token_counts[selected],
                    "wall_time_ms": elapsed_ms,
                    "tokenizer_fragmentation": fragmentation_ratio(tokenizer, probe["prompt"]),
                },
                "behavior": {
                    "raw_output_ref": str(raw_path),
                    "score": machine_score,
                    "selected_option": selected,
                    "option_scores": calibrated,
                    "consistency_group": probe["probe_id"],
                },
                "representation": None,
                "evidence_grade": "G0",
            }

            errors = sorted(validator.iter_errors(record), key=lambda err: list(err.path))
            if errors:
                formatted = "\n".join(f"{list(err.path)}: {err.message}" for err in errors)
                raise ValueError(f"Schema validation failed for {probe['surface_id']}:\n{formatted}")

            records_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            margin = calibrated[selected] - calibrated[
                "negative" if selected == "positive" else "positive"
            ]
            print(
                json.dumps(
                    {
                        "surface_id": probe["surface_id"],
                        "selected": selected,
                        "expected": expected,
                        "score": machine_score,
                        "calibrated_margin": round(margin, 6),
                    },
                    ensure_ascii=False,
                )
            )

    print(f"wrote {records_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
