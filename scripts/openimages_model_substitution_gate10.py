#!/usr/bin/env python3
"""Gate 10: direct-v0 model substitution on the same 24-image Open Images slice."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import requests

from external_presence_eval import aggregate_verified_rankings, load_mappings, score_verified_ranking
from openimages_treatment_gate7 import build_trials
from visual_concept_worker_core import CandidateSpec, canonical_digest, run_direct
from visual_concept_worker_ringer import PublicHFScorer


MODELS = {
    "clip": {
        "family": "clip",
        "model_id": "openai/clip-vit-base-patch32",
        "model_revision": "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268",
        "prompt_template": "a photo of a {}",
        "score_transform": "softmax",
        "text_padding": True,
    },
    "siglip": {
        "family": "siglip",
        "model_id": "google/siglip-base-patch16-224",
        "model_revision": "7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed",
        "prompt_template": "This is a photo of {}.",
        "score_transform": "sigmoid",
        "text_padding": "max_length",
    },
}


def make_candidate(model: dict, concepts: list[dict]) -> CandidateSpec:
    return CandidateSpec(
        worker_framework="visual-concept-worker",
        framework_version="0.1.0",
        backend_family=model["family"],
        model_id=model["model_id"],
        model_revision=model["model_revision"],
        concept_pack_digest=canonical_digest(concepts),
        action_policy="direct-v0",
        toolset=("score_concepts",),
        parameters={
            "prompt_template": model["prompt_template"],
            "score_transform": model["score_transform"],
            "text_padding": model["text_padding"],
            "top_k": len(concepts),
        },
    )


def main() -> int:
    source = json.loads(
        Path("data/external-benchmarks/openimages-v7-validation-source.json").read_text(
            encoding="utf-8"
        )
    )
    source["selection_rule"] = dict(source["selection_rule"])
    source["selection_rule"]["images"] = 24
    source["selection_rule"]["method"] = (
        "first 24 complete validation image groups in source order with at least "
        "two human-verified positive and two human-verified negative labels"
    )

    evaluation_protocol = {
        "view_scope": "whole",
        "score_field": "raw_score",
        "reducer": "single",
        "semantics": (
            "within-model ranking of one whole-image raw visual score per concept; "
            "raw values are not compared across model families"
        ),
    }

    with TemporaryDirectory(prefix="openimages-gate10-") as tmpdir:
        root = Path(tmpdir)
        trials, selected_labels = build_trials(source, root)
        concepts = [
            {"label": selected_labels[mid], "concept_id": f"openimages:{mid}"}
            for mid in sorted(selected_labels)
        ]
        mappings = load_mappings(
            [
                {
                    "dataset": "open-images",
                    "external_label_id": mid,
                    "worker_concept_id": f"openimages:{mid}",
                    "mapping": "exact",
                    "ground_truth_scope": source["ground_truth_scope"],
                }
                for mid in sorted(selected_labels)
            ]
        )

        images = {}
        for trial in trials:
            image_url = source["image_url_template"].format(image_id=trial["image_id"])
            response = requests.get(image_url, timeout=60)
            response.raise_for_status()
            image_path = root / f"{trial['image_id']}.jpg"
            image_path.write_bytes(response.content)
            images[trial["image_id"]] = image_path

        aggregate_inputs = {}
        per_model = {}
        candidate_digests = {}

        for name, model in MODELS.items():
            candidate = make_candidate(model, concepts)
            candidate_digests[name] = candidate.candidate_digest
            scorer = PublicHFScorer(
                {
                    "backend_family": model["family"],
                    "model_id": model["model_id"],
                    "model_revision": model["model_revision"],
                    "parameters": {
                        "prompt_template": model["prompt_template"],
                        "score_transform": model["score_transform"],
                        "text_padding": model["text_padding"],
                    },
                }
            )
            elapsed = 0.0
            scored_items = []
            trial_rows = []
            for trial in trials:
                start = perf_counter()
                worker = run_direct(
                    scorer=scorer,
                    candidate=candidate,
                    image_path=images[trial["image_id"]],
                    concepts=concepts,
                    top_k=len(concepts),
                    execution_lane="public-ringer",
                )
                elapsed += perf_counter() - start
                ranking = score_verified_ranking(
                    item=trial,
                    observations=worker["observations"],
                    mappings=mappings,
                    view_scope=evaluation_protocol["view_scope"],
                    score_field=evaluation_protocol["score_field"],
                    reducer=evaluation_protocol["reducer"],
                )
                scored_items.append(ranking)
                trial_rows.append(
                    {
                        "image_id": trial["image_id"],
                        "input_sha256": worker["input"]["sha256"],
                        "pairwise_accuracy": ranking["pairwise"]["accuracy"],
                        "positive_at_k_rate": ranking["positive_at_k"]["rate"],
                        "mean_positive_rank": ranking["mean_positive_rank"],
                    }
                )
            aggregate_inputs[name] = scored_items
            per_model[name] = {
                "family": model["family"],
                "model_id": model["model_id"],
                "model_revision": model["model_revision"],
                "candidate_digest": candidate.candidate_digest,
                "aggregate": aggregate_verified_rankings(scored_items),
                "resource_telemetry": {
                    "model_views": len(trials),
                    "seconds": elapsed,
                },
                "trials": trial_rows,
            }

    clip_ids = [row["input_sha256"] for row in per_model["clip"]["trials"]]
    siglip_ids = [row["input_sha256"] for row in per_model["siglip"]["trials"]]
    if clip_ids != siglip_ids:
        raise SystemExit("CLIP and SigLIP input identities differ")
    if len(set(candidate_digests.values())) != len(candidate_digests):
        raise SystemExit("model candidates do not have distinct identities")

    result = {
        "schema_version": "openimages_model_substitution_gate10.v0.1",
        "status": "pass",
        "dataset": "open-images-v7",
        "split": "validation",
        "selection_rule": source["selection_rule"],
        "concept_pack_size": len(concepts),
        "evaluation_protocol": evaluation_protocol,
        "models": per_model,
        "invariants": {
            "same_images": True,
            "same_external_labels": True,
            "same_concept_ids": True,
            "candidate_identity_separated": True,
            "raw_scores_compared_across_model_families": False,
            "classification_threshold_invented": False,
            "policy_ground_truth_claimed": False,
            "representative_population_claimed": False,
            "private_content_present": False,
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
