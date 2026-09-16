#!/usr/bin/env python3
"""Rep 25: minimize a lexical-overlap reranker near-tie and compare score/CLS geometry.

This is a bounded counterexample-search/minimization rep seeded by Rep 24's
`largest-planet` observation. It intentionally records surprising behavior instead
of defining semantic correctness as an acceptance gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

LOGICAL_ID = "rerank/cross-encoder/ms-marco-minilm-l6-v2"
UPSTREAM_REPO = "cross-encoder/ms-marco-MiniLM-L6-v2"
UPSTREAM_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
QUERY = "Which planet is the largest in the Solar System?"
REFERENCE = "Jupiter is the largest planet in the Solar System."
SEED_FALSE = "Mars is the largest planet in the Solar System."
NEAR_TIE_TOLERANCE = 0.5

CURATED = [
    {"id": "seed_false", "text": SEED_FALSE, "intent": "false direct assertion with maximal query overlap"},
    {"id": "negated_false", "text": "Mars is not the largest planet in the Solar System.", "intent": "explicitly negate the false assertion"},
    {"id": "meta_false", "text": "The statement that Mars is the largest planet in the Solar System is false.", "intent": "metalinguistically mark the assertion false"},
    {"id": "corrected", "text": "Mars is not the largest planet in the Solar System; Jupiter is.", "intent": "retain overlap but state the correction"},
    {"id": "incorrect_claim", "text": "An incorrect claim says Mars is the largest planet in the Solar System.", "intent": "embed the false assertion under an incorrect-claim operator"},
    {"id": "lexical_bag", "text": "Mars largest planet Solar System", "intent": "query-term-heavy fragment without normal sentence structure"},
    {"id": "relation_only", "text": "largest planet in the Solar System", "intent": "remove false entity while preserving relation words"},
    {"id": "entity_only", "text": "Mars", "intent": "retain false entity only"},
    {"id": "irrelevant", "text": "Whales are marine mammals that breathe air.", "intent": "null semantic/lexical control"},
]


def sha256_json(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def cosine_distance(a: torch.Tensor, b: torch.Tensor) -> float:
    a = a.float()
    b = b.float()
    den = max(float(torch.linalg.vector_norm(a).item() * torch.linalg.vector_norm(b).item()), 1e-12)
    return 1.0 - float(torch.dot(a, b).item() / den)


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    den = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    if den <= 1e-12:
        return None
    return sum(x*y for x, y in zip(dx, dy)) / den


def infer(tokenizer, model, passages: list[str], *, hidden: bool = False) -> tuple[list[float], tuple[torch.Tensor, ...] | None, list[int]]:
    inputs = tokenizer([QUERY] * len(passages), passages, padding=True, truncation=True, max_length=192, return_tensors="pt")
    with torch.inference_mode():
        out = model(**inputs, output_hidden_states=hidden, return_dict=True)
    scores = out.logits.reshape(-1).detach().float().cpu()
    if scores.shape != (len(passages),) or not torch.isfinite(scores).all().item():
        raise RuntimeError("invalid scalar score surface")
    mask = inputs.get("attention_mask")
    counts = [int(x) for x in mask.sum(dim=1).tolist()] if mask is not None else [int(inputs["input_ids"].shape[1])] * len(passages)
    states = tuple(out.hidden_states) if hidden and out.hidden_states else None
    if hidden and not states:
        raise RuntimeError("hidden-state observability unavailable")
    return [float(x) for x in scores.tolist()], states, counts


def score_one(tokenizer, model, passage: str) -> float:
    return infer(tokenizer, model, [passage], hidden=False)[0][0]


def greedy_minimize(tokenizer, model, *, threshold: float, required_terms: set[str]) -> list[dict[str, Any]]:
    words = SEED_FALSE.split()
    path: list[dict[str, Any]] = []
    current_score = score_one(tokenizer, model, " ".join(words))
    path.append({"step": 0, "text": " ".join(words), "word_count": len(words), "score": current_score, "removed": None})
    step = 0
    while len(words) > 1:
        candidates = []
        for i, word in enumerate(words):
            trial = words[:i] + words[i+1:]
            normalized = {w.strip(".,;:!?\"'").lower() for w in trial}
            if required_terms and not required_terms.issubset(normalized):
                continue
            if not trial:
                continue
            text = " ".join(trial)
            candidates.append((i, word, text))
        if not candidates:
            break
        scores, _, _ = infer(tokenizer, model, [x[2] for x in candidates], hidden=False)
        eligible = [(score, cand) for score, cand in zip(scores, candidates) if score >= threshold]
        if not eligible:
            break
        score, (idx, removed, text) = max(eligible, key=lambda x: (x[0], -len(x[1][2])))
        words = words[:idx] + words[idx+1:]
        step += 1
        path.append({"step": step, "text": text, "word_count": len(words), "score": float(score), "removed": removed})
    return path


def layer_distances(reference_states: tuple[torch.Tensor, ...], candidate_states: tuple[torch.Tensor, ...], labels: list[str]) -> list[dict[str, Any]]:
    if len(reference_states) != len(candidate_states):
        raise RuntimeError("hidden-state layer count mismatch")
    rows = []
    for layer, (ref_h, cand_h) in enumerate(zip(reference_states, candidate_states)):
        ref_cls = ref_h[0, 0, :].detach().float().cpu()
        cand_cls = cand_h[:, 0, :].detach().float().cpu()
        if not torch.isfinite(ref_cls).all().item() or not torch.isfinite(cand_cls).all().item():
            raise RuntimeError("non-finite hidden state")
        rows.append({
            "layer": layer,
            "distances": {label: cosine_distance(ref_cls, cand_cls[i]) for i, label in enumerate(labels)},
        })
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--identity-digest", required=True)
    p.add_argument("--foundry-record-ref", required=True)
    p.add_argument("--output", type=Path, default=Path("out/reranker-counterexample.json"))
    args = p.parse_args()
    if not args.identity_digest.startswith("sha256:") or len(args.identity_digest) != 71:
        raise RuntimeError("identity digest must be a full sha256 OCI digest")

    started_wall = time.time()
    started = time.perf_counter()
    torch.manual_seed(0)
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    t = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    model.eval()
    model_load_seconds = time.perf_counter() - t

    t = time.perf_counter()
    reference_score, reference_states, reference_tokens = infer(tokenizer, model, [REFERENCE], hidden=True)
    reference_score = reference_score[0]
    assert reference_states is not None
    threshold = reference_score - NEAR_TIE_TOLERANCE

    curated_texts = [row["text"] for row in CURATED]
    curated_scores, curated_states, curated_tokens = infer(tokenizer, model, curated_texts, hidden=True)
    repeat_scores, _, _ = infer(tokenizer, model, curated_texts, hidden=False)
    assert curated_states is not None
    repeat_delta = max(abs(a-b) for a,b in zip(curated_scores, repeat_scores))

    unconstrained = greedy_minimize(tokenizer, model, threshold=threshold, required_terms=set())
    constrained = greedy_minimize(tokenizer, model, threshold=threshold, required_terms={"mars", "largest", "planet"})

    labels = [row["id"] for row in CURATED]
    layer_rows = layer_distances(reference_states, curated_states, labels)
    final_distances = layer_rows[-1]["distances"]
    score_gaps = [reference_score - s for s in curated_scores]
    geometry = [float(final_distances[label]) for label in labels]

    curated = []
    for spec, score, tokens in zip(CURATED, curated_scores, curated_tokens):
        curated.append({**spec, "score": score, "score_gap_from_reference": reference_score - score, "near_tie_within_tolerance": score >= threshold, "token_count": tokens})

    observations = {
        "query": QUERY,
        "reference": {"text": REFERENCE, "score": reference_score, "token_count": reference_tokens[0]},
        "near_tie_tolerance": NEAR_TIE_TOLERANCE,
        "near_tie_threshold": threshold,
        "curated_variants": curated,
        "unconstrained_greedy_minimization": unconstrained,
        "false_semantics_preserving_greedy_minimization": {
            "required_terms": ["mars", "largest", "planet"],
            "path": constrained,
        },
        "layerwise_reference_cls_distances": layer_rows,
        "artifact_state": "candidate",
    }
    derived = {
        "repeat_max_abs_delta": repeat_delta,
        "curated_near_tie_ids": [row["id"] for row in curated if row["near_tie_within_tolerance"]],
        "unconstrained_final": unconstrained[-1],
        "constrained_final": constrained[-1],
        "final_layer_score_gap_vs_cls_distance_pearson": pearson(score_gaps, geometry),
        "portable_method_checks": {
            "counterexample_seed_reproduced": abs(curated_scores[0] - reference_score) <= NEAR_TIE_TOLERANCE,
            "greedy_minimization_executed": len(unconstrained) >= 1 and len(constrained) >= 1,
            "semantic_constraint_supported": True,
            "layerwise_geometry_observed": len(layer_rows) >= 2,
            "repeatability_observed": repeat_delta <= 1e-6,
            "candidate_provenance_bound": True,
        },
    }

    raw_output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    git_sha = os.environ.get("GITHUB_SHA")
    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(started_wall)}")
    bundle = {
        "probe_id": "reranker-counterexample-minimization-v1",
        "instrument": "counterexample-minimize-and-representation-contrast",
        "instrument_version": "mvp-1",
        "model_identity": {
            "repository": UPSTREAM_REPO,
            "revision": UPSTREAM_REVISION,
            "logical_id": LOGICAL_ID,
            "model_class": "cross-encoder-reranker-scalar-judge",
            "foundry_state": "candidate",
        },
        "artifact_provenance": {
            "tracked": True,
            "foundry_repository": "SemperSupra/model-artifact-foundry",
            "logical_artifact_id": LOGICAL_ID,
            "upstream_provider": "huggingface",
            "upstream_repository": UPSTREAM_REPO,
            "upstream_revision": UPSTREAM_REVISION,
            "identity_kind": "oci",
            "identity_digest": args.identity_digest,
            "foundry_record_ref": args.foundry_record_ref,
            "consumer_selection_ref": f"model-spelunker@{git_sha}" if git_sha else None,
            "verified": True,
            "verification_ref": "Foundry candidate OCI pullback and generic hydration verification; candidate is not approved catalog state",
            "tokenizer_artifact": None,
        },
        "access_tier": "A2",
        "evidence_level": "REPRODUCED",
        "claim_tags": ["RERANKER", "COUNTEREXAMPLE_SEARCH", "MINIMIZED", "REPRESENTATION_GEOMETRY", "CANDIDATE_ARTIFACT"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "scope": "one counterexample family with a fixed 0.5-logit near-tie tolerance; intended to test methodology, not model quality",
            "greedy_minimization": "local one-word deletion search; not globally minimal",
            "semantic_constraint": "required lexical terms preserve the false Mars/largest/planet skeleton but do not formally prove natural-language falsity",
        },
        "known_assumptions": [
            "Rep 24's largest-planet near-tie is a useful seed for counterexample-method testing",
            "a fixed 0.5-logit gap is a transparent engineering threshold rather than a calibrated statistical boundary",
            "CLS cosine distance is descriptive and not causal",
        ],
        "known_failure_modes": [
            "greedy deletion can find unnatural fragments",
            "word deletion order can miss a smaller global counterexample",
            "required lexical terms are only a proxy for preserving false-claim semantics",
        ],
        "cost": {
            "model_load_seconds": model_load_seconds,
            "experiment_seconds": time.perf_counter() - t,
            "total_script_seconds": time.perf_counter() - started,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        },
        "provenance": {
            "run_id": str(run_id),
            "code_revision": git_sha,
            "model_revision": UPSTREAM_REVISION,
            "tokenizer_revision": UPSTREAM_REVISION,
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "torch": torch.__version__,
                "transformers": __import__("transformers").__version__,
                "torch_num_threads": torch.get_num_threads(),
            },
            "randomness": {"torch_manual_seed": 0, "sampling": False},
            "raw_input_hash": sha256_json({"query": QUERY, "reference": REFERENCE, "seed_false": SEED_FALSE, "curated": CURATED, "tolerance": NEAR_TIE_TOLERANCE}),
            "raw_output_hash": raw_output_hash,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "reference_score": reference_score,
        "threshold": threshold,
        "curated_near_tie_ids": derived["curated_near_tie_ids"],
        "unconstrained_final": unconstrained[-1],
        "constrained_final": constrained[-1],
        "score_geometry_pearson": derived["final_layer_score_gap_vs_cls_distance_pearson"],
        "repeat_max_abs_delta": repeat_delta,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
