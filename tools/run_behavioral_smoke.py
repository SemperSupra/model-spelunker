#!/usr/bin/env python3
"""CPU-only behavioral scorer for Experiment 0001.

This is intentionally small. It scores fixed candidate continuations by conditional
log likelihood, counterbalances A/B label mappings, writes raw evidence separately,
and emits schema-validated Concept Geometry Records. It does not claim mechanistic
interpretation.
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
PROMPT_TEMPLATE_VERSION = "choice-score-v0.2-counterbalanced"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="fixtures/experiment-0001/reciprocity-smoke.jsonl")
    parser.add_argument("--schema", default="schemas/concept-geometry-record.schema.json")
    parser.add_argument("--model", default="EleutherAI/pythia-70m")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--output-dir", default="artifacts/experiment-0001")
    parser.add_argument("--max-probes", type=int, default=0, help="0 means all semantic probes")
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


def swap_ab_mapping(prompt: str) -> str:
    """Swap the right-hand sides of A/B mapping lines without changing the question."""
    lines = prompt.splitlines()
    a_index = next((i for i, line in enumerate(lines) if line.startswith("A = ")), None)
    b_index = next((i for i, line in enumerate(lines) if line.startswith("B = ")), None)
    if a_index is None or b_index is None:
        raise ValueError("Counterbalancing requires prompt lines beginning with 'A = ' and 'B = '")
    a_value = lines[a_index][4:]
    b_value = lines[b_index][4:]
    lines[a_index] = f"A = {b_value}"
    lines[b_index] = f"B = {a_value}"
    return "\n".join(lines)


def semanticize(raw_option: str, mapping: str) -> str:
    """Map the observed A/B label back to the original semantic option identity."""
    if mapping == "AB":
        return raw_option
    if mapping == "BA":
        return " B" if raw_option == " A" else " A"
    raise ValueError(f"Unknown mapping: {mapping}")


def semanticize_scores(raw_scores: dict[str, float], mapping: str) -> dict[str, float]:
    if mapping == "AB":
        return dict(raw_scores)
    if mapping == "BA":
        return {" A": raw_scores[" B"], " B": raw_scores[" A"]}
    raise ValueError(f"Unknown mapping: {mapping}")


def conditional_mean_logprob(
    model: AutoModelForCausalLM,
    tokenizer: AutoTokenizer,
    prompt: str,
    candidate: str,
) -> tuple[float, int]:
    prompt_ids = tokenizer(prompt, add_special_tokens=False, return_tensors="pt").input_ids
    full_ids = tokenizer(prompt + candidate, add_special_tokens=False, return_tensors="pt").input_ids

    prompt_len = prompt_ids.shape[1]
    full_len = full_ids.shape[1]
    candidate_tokens = full_len - prompt_len
    if candidate_tokens <= 0:
        raise ValueError(f"Candidate produced no additional tokens: {candidate!r}")

    with torch.inference_mode():
        logits = model(full_ids).logits
        log_probs = torch.log_softmax(logits, dim=-1)

    token_logps: list[float] = []
    for token_position in range(prompt_len, full_len):
        prediction_position = token_position - 1
        target_id = int(full_ids[0, token_position])
        token_logps.append(float(log_probs[0, prediction_position, target_id]))

    return sum(token_logps) / len(token_logps), candidate_tokens


def fragmentation_ratio(tokenizer: AutoTokenizer, prompt: str) -> float:
    token_count = len(tokenizer(prompt, add_special_tokens=False).input_ids)
    nonspace_chars = sum(1 for char in prompt if not char.isspace())
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
        "semantic_probe_count": len(probes),
        "counterbalanced_record_count": len(probes) * 2,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with records_path.open("w", encoding="utf-8") as records_file:
        for probe in probes:
            variants = [
                ("AB", probe["prompt"]),
                ("BA", swap_ab_mapping(probe["prompt"])),
            ]
            rng.shuffle(variants)

            for mapping, prompt in variants:
                started = time.perf_counter()
                raw_option_scores: dict[str, float] = {}
                option_token_counts: dict[str, int] = {}
                for option in probe["options"]:
                    score, option_tokens = conditional_mean_logprob(model, tokenizer, prompt, option)
                    raw_option_scores[option] = score
                    option_token_counts[option] = option_tokens

                raw_selected = max(raw_option_scores, key=raw_option_scores.get)
                semantic_selected = semanticize(raw_selected, mapping)
                semantic_scores = semanticize_scores(raw_option_scores, mapping)
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                expected = probe.get("expected")
                machine_score = None if expected is None else float(semantic_selected == expected)

                variant_surface_id = f"{probe['surface_id']}-{mapping.lower()}"
                raw_path = raw_dir / f"{variant_surface_id}.json"
                raw_payload = {
                    "surface_id": variant_surface_id,
                    "base_surface_id": probe["surface_id"],
                    "counterbalance": mapping,
                    "prompt": prompt,
                    "options": probe["options"],
                    "expected_semantic_option": expected,
                    "raw_selected_option": raw_selected,
                    "semantic_selected_option": semantic_selected,
                    "raw_option_scores": raw_option_scores,
                    "semantic_option_scores": semantic_scores,
                    "option_token_counts": option_token_counts,
                }
                raw_path.write_text(
                    json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )

                input_tokens = len(tokenizer(prompt, add_special_tokens=False).input_ids)
                output_tokens = option_token_counts[raw_selected]

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
                        "surface_id": variant_surface_id,
                        "class": probe["class"],
                        "language": probe["language"],
                        "formulation_type": probe["formulation_type"],
                        "source": probe["source"],
                        "translation_path": probe.get("translation_path"),
                    },
                    "run": {
                        "seed": args.seed,
                        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "wall_time_ms": elapsed_ms,
                        "tokenizer_fragmentation": fragmentation_ratio(tokenizer, prompt),
                    },
                    "behavior": {
                        "raw_output_ref": str(raw_path),
                        "score": machine_score,
                        "selected_option": semantic_selected,
                        "option_scores": semantic_scores,
                        "consistency_group": probe["surface_id"],
                    },
                    "representation": None,
                    "evidence_grade": "G0",
                }

                errors = sorted(validator.iter_errors(record), key=lambda err: list(err.path))
                if errors:
                    formatted = "\n".join(f"{list(err.path)}: {err.message}" for err in errors)
                    raise ValueError(f"Schema validation failed for {variant_surface_id}:\n{formatted}")

                records_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(
                    json.dumps(
                        {
                            "surface_id": variant_surface_id,
                            "counterbalance": mapping,
                            "raw_selected": raw_selected.strip(),
                            "semantic_selected": semantic_selected.strip(),
                            "expected": None if expected is None else expected.strip(),
                            "score": machine_score,
                            "semantic_margin": round(
                                max(semantic_scores.values()) - min(semantic_scores.values()), 6
                            ),
                        },
                        ensure_ascii=False,
                    )
                )

    print(f"wrote {records_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
