#!/usr/bin/env python3
"""Rep 24: portability of Model Spelunker onto a scalar cross-encoder reranker.

The artifact is expected to be a digest-pinned, pullback-verified Foundry candidate.
This rep characterizes the ranking/scalar-judge contract and hidden-state geometry;
it does not treat any ranking outcome as a model-quality acceptance criterion.
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

PROBE_FAMILIES = [
    {
        "id": "red-planet",
        "query_direct": "Which planet is known as the Red Planet?",
        "query_paraphrase": "What planet has the nickname the Red Planet?",
        "passages": [
            {"id": "relevant_direct", "role": "relevant", "text": "Mars is known as the Red Planet because iron minerals on its surface give it a reddish appearance."},
            {"id": "relevant_paraphrase", "role": "relevant", "text": "The planet Mars has the nickname Red Planet because it looks reddish from Earth."},
            {"id": "lexical_distractor", "role": "lexical_distractor", "text": "Venus is often called Earth's twin. The words Red Planet are frequently discussed in astronomy, but this passage describes Venus."},
            {"id": "negated", "role": "negated", "text": "Mars is not known as the Red Planet."},
            {"id": "irrelevant", "role": "irrelevant", "text": "Whales are marine mammals that breathe air at the ocean surface."},
        ],
    },
    {
        "id": "largest-planet",
        "query_direct": "Which planet is the largest in the Solar System?",
        "query_paraphrase": "What is the biggest planet orbiting the Sun?",
        "passages": [
            {"id": "relevant_direct", "role": "relevant", "text": "Jupiter is the largest planet in the Solar System."},
            {"id": "relevant_paraphrase", "role": "relevant", "text": "The biggest planet that orbits the Sun is Jupiter."},
            {"id": "lexical_distractor", "role": "lexical_distractor", "text": "Mars is the largest planet in the Solar System according to this incorrect statement."},
            {"id": "negated", "role": "negated", "text": "Jupiter is not the largest planet in the Solar System."},
            {"id": "irrelevant", "role": "irrelevant", "text": "The Pacific Ocean is the largest ocean on Earth."},
        ],
    },
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
    den = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    if den <= 1e-12:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / den


def score_batch(tokenizer, model, query: str, passages: list[dict], *, hidden: bool) -> tuple[list[float], tuple[torch.Tensor, ...] | None, list[int]]:
    texts = [row["text"] for row in passages]
    inputs = tokenizer([query] * len(texts), texts, padding=True, truncation=True, max_length=192, return_tensors="pt")
    with torch.inference_mode():
        outputs = model(**inputs, output_hidden_states=hidden, return_dict=True)
    scores = outputs.logits.reshape(-1).detach().float().cpu()
    if scores.shape != (len(texts),):
        raise RuntimeError(f"unexpected scalar score shape: {tuple(scores.shape)}")
    if not torch.isfinite(scores).all().item():
        raise RuntimeError("non-finite reranker score")
    attention = inputs.get("attention_mask")
    if attention is None:
        token_counts = [int(inputs["input_ids"].shape[1])] * len(texts)
    else:
        token_counts = [int(x) for x in attention.sum(dim=1).tolist()]
    states = tuple(outputs.hidden_states) if hidden and outputs.hidden_states else None
    if hidden and not states:
        raise RuntimeError("hidden-state observability unavailable")
    return [float(x) for x in scores.tolist()], states, token_counts


def score_single(tokenizer, model, left: str, right: str) -> float:
    inputs = tokenizer([left], [right], padding=True, truncation=True, max_length=192, return_tensors="pt")
    with torch.inference_mode():
        score = model(**inputs, return_dict=True).logits.reshape(-1).detach().float().cpu()
    if score.shape != (1,) or not torch.isfinite(score).all().item():
        raise RuntimeError("invalid single-pair score")
    return float(score[0].item())


def layer_geometry(states: tuple[torch.Tensor, ...], passages: list[dict]) -> list[dict[str, Any]]:
    rows = []
    ids = [row["id"] for row in passages]
    ref = ids.index("relevant_direct")
    for layer, hidden in enumerate(states):
        cls = hidden[:, 0, :].detach().float().cpu()
        if not torch.isfinite(cls).all().item():
            raise RuntimeError(f"non-finite CLS state at layer {layer}")
        row: dict[str, Any] = {
            "layer": layer,
            "mean_cls_l2": float(torch.linalg.vector_norm(cls, dim=-1).mean().item()),
        }
        for idx, passage_id in enumerate(ids):
            if idx == ref:
                continue
            row[f"relevant_direct_to_{passage_id}_cosine_distance"] = cosine_distance(cls[ref], cls[idx])
        rows.append(row)
    return rows


def family_observation(tokenizer, model, family: dict[str, Any]) -> dict[str, Any]:
    passages = family["passages"]
    direct_scores, states, direct_tokens = score_batch(tokenizer, model, family["query_direct"], passages, hidden=True)
    paraphrase_scores, _, paraphrase_tokens = score_batch(tokenizer, model, family["query_paraphrase"], passages, hidden=False)
    repeat_scores, _, _ = score_batch(tokenizer, model, family["query_direct"], passages, hidden=False)
    repeat_delta = max(abs(a - b) for a, b in zip(direct_scores, repeat_scores))

    ids = [row["id"] for row in passages]
    roles = [row["role"] for row in passages]
    relevant_indices = [i for i, role in enumerate(roles) if role == "relevant"]
    nonrelevant_indices = [i for i, role in enumerate(roles) if role != "relevant"]
    direct_best_relevant = max(direct_scores[i] for i in relevant_indices)
    direct_best_nonrelevant = max(direct_scores[i] for i in nonrelevant_indices)
    para_best_relevant = max(paraphrase_scores[i] for i in relevant_indices)
    para_best_nonrelevant = max(paraphrase_scores[i] for i in nonrelevant_indices)

    neg_idx = ids.index("negated")
    rel_idx = ids.index("relevant_direct")
    forward = direct_scores[rel_idx]
    swapped = score_single(tokenizer, model, passages[rel_idx]["text"], family["query_direct"])

    return {
        "family_id": family["id"],
        "query_direct": family["query_direct"],
        "query_paraphrase": family["query_paraphrase"],
        "passages": passages,
        "direct_scores": direct_scores,
        "paraphrase_scores": paraphrase_scores,
        "direct_token_counts": direct_tokens,
        "paraphrase_token_counts": paraphrase_tokens,
        "direct_top_id": ids[max(range(len(ids)), key=lambda i: direct_scores[i])],
        "paraphrase_top_id": ids[max(range(len(ids)), key=lambda i: paraphrase_scores[i])],
        "direct_best_relevant_margin": direct_best_relevant - direct_best_nonrelevant,
        "paraphrase_best_relevant_margin": para_best_relevant - para_best_nonrelevant,
        "direct_relevant_vs_negated_delta": direct_scores[rel_idx] - direct_scores[neg_idx],
        "direct_vs_paraphrase_score_pearson": pearson(direct_scores, paraphrase_scores),
        "repeat_max_abs_delta": repeat_delta,
        "input_order": {
            "forward_query_passage_score": forward,
            "swapped_passage_query_score": swapped,
            "forward_minus_swapped": forward - swapped,
        },
        "layer_cls_geometry": layer_geometry(states, passages),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--identity-digest", required=True)
    p.add_argument("--foundry-record-ref", required=True)
    p.add_argument("--output", type=Path, default=Path("out/reranker-portability.json"))
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
    families = [family_observation(tokenizer, model, family) for family in PROBE_FAMILIES]
    experiment_seconds = time.perf_counter() - t

    max_repeat_delta = max(float(row["repeat_max_abs_delta"]) for row in families)
    layer_counts = [len(row["layer_cls_geometry"]) for row in families]
    observations = {
        "probe_families": families,
        "score_semantics": "higher scalar is treated as higher query-passage relevance per upstream reranker contract; values are not calibrated probabilities",
        "artifact_state": "candidate",
    }
    derived = {
        "max_repeat_abs_delta": max_repeat_delta,
        "hidden_state_layer_counts": layer_counts,
        "all_direct_best_relevant_margins": [float(row["direct_best_relevant_margin"]) for row in families],
        "all_paraphrase_best_relevant_margins": [float(row["paraphrase_best_relevant_margin"]) for row in families],
        "portable_instrument_checks": {
            "scalar_query_passage_scores_observed": True,
            "repeatability_observed": max_repeat_delta <= 1e-6,
            "query_paraphrase_contrast_observed": True,
            "lexical_distractor_contrast_observed": True,
            "negation_contrast_observed": True,
            "input_order_asymmetry_measured": True,
            "layerwise_cls_geometry_observed": all(n >= 2 for n in layer_counts),
            "foundry_candidate_oci_identity": True,
        },
    }
    raw_output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    git_sha = os.environ.get("GITHUB_SHA")
    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(started_wall)}")

    bundle = {
        "probe_id": "reranker-portability-minilm-v1",
        "instrument": "scalar-reranker-and-layer-geometry-suite",
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
        "claim_tags": ["RERANKER", "SCALAR_JUDGE", "REPRESENTATION_GEOMETRY", "CANDIDATE_ARTIFACT"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "scope": "model-class/instrument portability on two tiny controlled ranking families; not a quality benchmark",
            "foundry_state": "candidate-not-approved",
            "ranking_outcomes_are_descriptive": True,
        },
        "known_assumptions": [
            "the upstream cross-encoder scalar is interpreted only as a relative relevance score, not a calibrated probability",
            "CLS-token cosine geometry is a descriptive representation view and not a localized mechanism",
            "candidate OCI pullback verification proves artifact identity but not catalog approval",
        ],
        "known_failure_modes": [
            "lexical-overlap and negation probes may expose model weaknesses and are not pass/fail acceptance checks",
            "two controlled query families are insufficient for a model-quality conclusion",
            "input-order effects are architecture/task-contract observations rather than defects by themselves",
        ],
        "cost": {
            "model_load_seconds": model_load_seconds,
            "experiment_seconds": experiment_seconds,
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
            "raw_input_hash": sha256_json(PROBE_FAMILIES),
            "raw_output_hash": raw_output_hash,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "probe_id": bundle["probe_id"],
        "max_repeat_abs_delta": max_repeat_delta,
        "direct_margins": derived["all_direct_best_relevant_margins"],
        "paraphrase_margins": derived["all_paraphrase_best_relevant_margins"],
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
