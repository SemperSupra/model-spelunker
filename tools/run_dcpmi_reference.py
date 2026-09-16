#!/usr/bin/env python3
"""Reference CPU Domain Conditional PMI scorer for Experiment 0001.

Implements the core scoring primitive from Holtzman et al. (2021):

    DC-PMI(option) = CE_domain(option) - CE_instance(option)

where CE is summed token cross-entropy for the same answer surface form. This
compensates for answer-string surface-form competition without using arbitrary
content-free calibration stems. The runner repeats the complete measurement in
one process and fails if selections are not numerically repeatable.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from reference_cpu import (
    NUMERIC_MODE,
    configure_reference_cpu,
    prepare_reference_model,
    runtime_fingerprint,
)

import huggingface_hub
import torch
import transformers
from huggingface_hub import model_info
from transformers import AutoModelForCausalLM, AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        default="fixtures/experiment-0001/reciprocity-dcpmi-heldout.jsonl",
    )
    parser.add_argument("--model", default="EleutherAI/pythia-70m")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output-dir", default="artifacts/experiment-0001-dcpmi-reference")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def text_metrics(tokenizer: AutoTokenizer, text: str) -> dict[str, float | int]:
    tokens = len(tokenizer(text, add_special_tokens=False).input_ids)
    chars = len(text)
    nonspace = sum(1 for char in text if not char.isspace())
    utf8_bytes = len(text.encode("utf-8"))
    return {
        "tokens": tokens,
        "unicode_chars": chars,
        "nonspace_chars": nonspace,
        "utf8_bytes": utf8_bytes,
        "tokens_per_nonspace_char": tokens / max(1, nonspace),
        "tokens_per_utf8_byte": tokens / max(1, utf8_bytes),
    }


def conditional_nll_sum(
    model: AutoModelForCausalLM,
    tokenizer: AutoTokenizer,
    source: str,
    target: str,
) -> tuple[float, int]:
    """Summed target-token NLL using separately tokenized source and target.

    Separate tokenization mirrors the reference Surface Form Competition code,
    which concatenates encoded source and target token sequences and sums target
    cross-entropy rather than averaging it.
    """
    source_ids = tokenizer(source, add_special_tokens=False).input_ids
    target_ids = tokenizer(target, add_special_tokens=False).input_ids
    if not source_ids:
        raise ValueError("DC-PMI source prompt must contain at least one token")
    if not target_ids:
        raise ValueError("DC-PMI answer surface must contain at least one token")

    ids = torch.tensor([source_ids + target_ids], dtype=torch.long)
    with torch.no_grad():
        logits = model(ids).logits[0]
        log_probs = torch.log_softmax(logits, dim=-1)

    start = len(source_ids) - 1
    losses = []
    for offset, token_id in enumerate(target_ids):
        losses.append(-log_probs[start + offset, token_id])
    return float(torch.stack(losses).sum().item()), len(target_ids)


def score_probe(
    model: AutoModelForCausalLM,
    tokenizer: AutoTokenizer,
    probe: dict[str, Any],
) -> dict[str, Any]:
    candidates = {
        "positive": probe["positive_continuation"],
        "negative": probe["negative_continuation"],
    }
    conditional_nll: dict[str, float] = {}
    domain_nll: dict[str, float] = {}
    token_counts: dict[str, int] = {}
    dcpmi: dict[str, float] = {}

    for name, answer in candidates.items():
        c_nll, c_tokens = conditional_nll_sum(model, tokenizer, probe["prompt"], answer)
        d_nll, d_tokens = conditional_nll_sum(model, tokenizer, probe["domain_prompt"], answer)
        if c_tokens != d_tokens:
            raise RuntimeError("Candidate token count changed across contexts")
        conditional_nll[name] = c_nll
        domain_nll[name] = d_nll
        token_counts[name] = c_tokens
        dcpmi[name] = d_nll - c_nll

    selected = max(dcpmi, key=dcpmi.get)
    other = "negative" if selected == "positive" else "positive"
    raw_selected = min(conditional_nll, key=conditional_nll.get)
    domain_selected = min(domain_nll, key=domain_nll.get)
    expected = probe.get("expected")

    return {
        "concept_id": probe["concept_id"],
        "probe_id": probe["probe_id"],
        "surface_id": probe["surface_id"],
        "class": probe["class"],
        "language": probe["language"],
        "source": probe["source"],
        "translation_path": probe.get("translation_path"),
        "expected": expected,
        "selected": selected,
        "raw_lm_selected": raw_selected,
        "domain_prior_selected": domain_selected,
        "score": None if expected is None else float(selected == expected),
        "conditional_nll": conditional_nll,
        "domain_nll": domain_nll,
        "dcpmi": dcpmi,
        "signed_margin_positive_minus_negative": dcpmi["positive"] - dcpmi["negative"],
        "winner_margin": dcpmi[selected] - dcpmi[other],
        "candidate_token_counts": token_counts,
        "prompt_metrics": text_metrics(tokenizer, probe["prompt"]),
        "domain_prompt_metrics": text_metrics(tokenizer, probe["domain_prompt"]),
        "candidate_metrics": {
            name: text_metrics(tokenizer, answer) for name, answer in candidates.items()
        },
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in rows if row["score"] is not None]
    by_language: dict[str, Any] = {}
    for language in sorted({row["language"] for row in rows}):
        group = [row for row in rows if row["language"] == language]
        scored = [row for row in group if row["score"] is not None]
        by_language[language] = {
            "n": len(group),
            "accuracy": None if not scored else mean(row["score"] for row in scored),
            "selection_counts": dict(Counter(row["selected"] for row in group)),
            "raw_lm_selection_counts": dict(Counter(row["raw_lm_selected"] for row in group)),
            "domain_prior_selection_counts": dict(Counter(row["domain_prior_selected"] for row in group)),
            "mean_input_tokens": mean(row["prompt_metrics"]["tokens"] for row in group),
            "mean_tokens_per_nonspace_char": mean(
                row["prompt_metrics"]["tokens_per_nonspace_char"] for row in group
            ),
            "mean_tokens_per_utf8_byte": mean(
                row["prompt_metrics"]["tokens_per_utf8_byte"] for row in group
            ),
        }

    by_probe_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_probe_id[row["probe_id"]].append(row)
    groups = [group for group in by_probe_id.values() if len(group) > 1]
    unanimous = [group for group in groups if len({row["selected"] for row in group}) == 1]

    return {
        "probe_count": len(rows),
        "accuracy": None if not labeled else mean(row["score"] for row in labeled),
        "cross_language_group_count": len(groups),
        "cross_language_unanimous_rate": None if not groups else len(unanimous) / len(groups),
        "by_language": by_language,
    }


def compare_repeats(repeats: list[list[dict[str, Any]]]) -> dict[str, Any]:
    maps = [{row["surface_id"]: row for row in rows} for rows in repeats]
    surfaces = sorted(maps[0])
    if any(sorted(mapping) != surfaces for mapping in maps[1:]):
        raise ValueError("Repeat probe sets differ")

    details = []
    stable = 0
    drifts = []
    for surface in surfaces:
        rows = [mapping[surface] for mapping in maps]
        margins = [row["signed_margin_positive_minus_negative"] for row in rows]
        selections = [row["selected"] for row in rows]
        drift = max(margins) - min(margins)
        is_stable = len(set(selections)) == 1
        stable += int(is_stable)
        drifts.append(drift)
        details.append(
            {
                "surface_id": surface,
                "language": rows[0]["language"],
                "margins": margins,
                "margin_drift": drift,
                "selections": selections,
                "selection_stable": is_stable,
            }
        )
    return {
        "repeat_count": len(repeats),
        "selection_agreement_rate": stable / len(surfaces),
        "max_margin_drift": max(drifts, default=0.0),
        "mean_margin_drift": mean(drifts) if drifts else 0.0,
        "exact_margin_repeatability": all(drift == 0.0 for drift in drifts),
        "per_probe": details,
    }


def main() -> int:
    args = parse_args()
    if args.repeats < 2:
        raise ValueError("Reference gate requires at least two repeats")
    configure_reference_cpu(args.seed)

    fixture = Path(args.fixture)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    probes = sorted(read_jsonl(fixture), key=lambda row: row["surface_id"])

    info = model_info(args.model, revision=args.revision)
    resolved_revision = info.sha
    if not resolved_revision:
        raise RuntimeError(f"Could not resolve immutable revision for {args.model}@{args.revision}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=resolved_revision)
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=resolved_revision)
    prepare_reference_model(model)

    repeats: list[list[dict[str, Any]]] = []
    for repeat_index in range(args.repeats):
        rows = [score_probe(model, tokenizer, probe) for probe in probes]
        repeats.append(rows)
        with (output_dir / f"repeat-{repeat_index + 1:02d}.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    repeatability = compare_repeats(repeats)
    summary = {
        "method": "domain-conditional-pmi",
        "method_reference": "Holtzman et al. 2021, Surface Form Competition",
        "numeric_mode": NUMERIC_MODE,
        "model": args.model,
        "requested_revision": args.revision,
        "resolved_revision": resolved_revision,
        "fixture": str(fixture),
        "seed": args.seed,
        "runtime": runtime_fingerprint(),
        "packages": {
            "transformers": transformers.__version__,
            "huggingface_hub": huggingface_hub.__version__,
        },
        "primary": summarize(repeats[0]),
        "intra_runner_repeatability": repeatability,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if repeatability["selection_agreement_rate"] < 1.0:
        raise RuntimeError("DC-PMI reference selections were not repeatable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
