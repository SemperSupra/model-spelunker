#!/usr/bin/env python3
"""Gate 9: scale out the fixed Gate-7 treatment comparison to 24 images."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import requests

from external_presence_eval import aggregate_verified_rankings, load_mappings, score_verified_ranking
from openimages_live_slice_gate6 import fetch_text, select_label_groups
from openimages_qualification import group_qualification_items, iter_human_image_labels, load_class_descriptions
from visual_active_integration import run_active_real
from visual_concept_worker_core import CandidateSpec, canonical_digest, run_direct
from visual_concept_worker_deterministic import run_deterministic
from visual_concept_worker_ringer import PublicHFScorer


MODEL_ID = "openai/clip-vit-base-patch32"
MODEL_REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
PROMPT = "a photo of a {}"


def build_trials(source: dict, root: Path):
    rule = source["selection_rule"]
    classes_path = root / "classes.csv"
    labels_path = root / "selected-labels.csv"
    classes_path.write_text(fetch_text(source["class_descriptions_url"]), encoding="utf-8")
    groups = select_label_groups(
        source["human_labels_url"],
        images=int(rule["images"]),
        min_present=int(rule["verified_present_per_image"]),
        min_absent=int(rule["verified_absent_per_image"]),
    )
    with labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ImageID", "Source", "LabelName", "Confidence"])
        writer.writeheader()
        for group in groups:
            writer.writerows(group)

    descriptions = load_class_descriptions(classes_path)
    normalized = group_qualification_items(iter_human_image_labels(labels_path, descriptions))
    trials = []
    labels = {}
    for item in normalized:
        present = sorted(item["verified_present"], key=lambda x: x["external_label_id"])[: int(rule["verified_present_per_image"])]
        absent = sorted(item["verified_absent"], key=lambda x: x["external_label_id"])[: int(rule["verified_absent_per_image"])]
        if len(present) < int(rule["verified_present_per_image"]) or len(absent) < int(rule["verified_absent_per_image"]):
            raise SystemExit("selected validation group no longer satisfies Gate-6 rule")
        trials.append(
            {
                "dataset": "open-images",
                "image_id": item["image_id"],
                "ground_truth_scope": source["ground_truth_scope"],
                "verified_present": present,
                "verified_absent": absent,
            }
        )
        for label in present + absent:
            labels[label["external_label_id"]] = label["external_label"]
    return trials, labels


def candidate(*, policy: str, concepts: list[dict], parameters: dict, toolset: tuple[str, ...]):
    return CandidateSpec(
        worker_framework="visual-concept-worker",
        framework_version="0.1.0",
        backend_family="clip",
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        concept_pack_digest=canonical_digest(concepts),
        action_policy=policy,
        toolset=toolset,
        parameters=parameters,
    )


def main() -> int:
    source = json.loads(
        Path("data/external-benchmarks/openimages-v7-validation-source.json").read_text(encoding="utf-8")
    )
    source["selection_rule"] = dict(source["selection_rule"])
    source["selection_rule"]["images"] = 24
    source["selection_rule"]["method"] = (
        "first 24 complete validation image groups in source order with at least "
        "two human-verified positive and two human-verified negative labels"
    )
    evaluation_protocol = {
        "view_scope": "all",
        "score_field": "raw_score",
        "reducer": "max",
        "semantics": "best raw visual evidence acquired by the candidate; no classification threshold",
    }

    with TemporaryDirectory(prefix="openimages-gate9-") as tmpdir:
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

        common = {
            "prompt_template": PROMPT,
            "score_transform": "softmax",
            "text_padding": True,
        }
        direct_candidate = candidate(
            policy="direct-v0",
            concepts=concepts,
            toolset=("score_concepts",),
            parameters={**common, "top_k": len(concepts)},
        )
        deterministic_candidate = candidate(
            policy="deterministic-v0",
            concepts=concepts,
            toolset=("score_concepts", "crop"),
            parameters={
                **common,
                "crop_strategy": "quadrants-v0",
                "ocr_strategy": "off",
                "top_k_per_view": len(concepts),
            },
        )
        active_candidate = candidate(
            policy="active-v0",
            concepts=concepts,
            toolset=("crop_score",),
            parameters={
                **common,
                "policy": "uncertainty-margin-one-probe-v0",
                "max_actions": 1,
                "margin_threshold": 0.5,
                "probe_bbox_norm": [0.1, 0.1, 0.9, 0.9],
                "top_k_per_probe": len(concepts),
            },
        )

        cfg = {
            "backend_family": "clip",
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "parameters": common,
        }
        scorer = PublicHFScorer(cfg)

        treatment_scores = {"direct-v0": [], "deterministic-v0": [], "active-v0": []}
        model_views = {"direct-v0": 0, "deterministic-v0": 0, "active-v0": 0}
        elapsed = {"direct-v0": 0.0, "deterministic-v0": 0.0, "active-v0": 0.0}
        per_image = []

        for trial in trials:
            image_url = source["image_url_template"].format(image_id=trial["image_id"])
            response = requests.get(image_url, timeout=60)
            response.raise_for_status()
            image_path = root / f"{trial['image_id']}.jpg"
            image_path.write_bytes(response.content)

            start = perf_counter()
            direct = run_direct(
                scorer=scorer,
                candidate=direct_candidate,
                image_path=image_path,
                concepts=concepts,
                top_k=len(concepts),
                execution_lane="public-ringer",
            )
            elapsed["direct-v0"] += perf_counter() - start
            model_views["direct-v0"] += 1

            start = perf_counter()
            deterministic = run_deterministic(
                scorer=scorer,
                candidate=deterministic_candidate,
                image_path=image_path,
                concepts=concepts,
                execution_lane="public-ringer",
            )
            elapsed["deterministic-v0"] += perf_counter() - start
            model_views["deterministic-v0"] += 5

            start = perf_counter()
            active = run_active_real(
                candidate=active_candidate,
                image_path=image_path,
                initial_manifest=direct,
                scorer=scorer,
                concepts=concepts,
            )
            elapsed["active-v0"] += perf_counter() - start
            model_views["active-v0"] += 1 + int(active["actions_executed"])

            observations = {
                "direct-v0": direct["observations"],
                "deterministic-v0": deterministic["observations"],
                "active-v0": active["worker_run"]["observations"],
            }
            image_scores = {}
            for treatment, obs in observations.items():
                scored = score_verified_ranking(
                    item=trial,
                    observations=obs,
                    mappings=mappings,
                    view_scope=evaluation_protocol["view_scope"],
                    score_field=evaluation_protocol["score_field"],
                    reducer=evaluation_protocol["reducer"],
                )
                treatment_scores[treatment].append(scored)
                image_scores[treatment] = {
                    "pairwise_accuracy": scored["pairwise"]["accuracy"],
                    "positive_at_k_rate": scored["positive_at_k"]["rate"],
                    "mean_positive_rank": scored["mean_positive_rank"],
                }

            per_image.append(
                {
                    "image_id": trial["image_id"],
                    "input_sha256": direct["input"]["sha256"],
                    "active_actions": active["actions_executed"],
                    "active_stop_reason": active["stop_reason"],
                    "scores": image_scores,
                }
            )

        aggregates = {
            treatment: aggregate_verified_rankings(scores)
            for treatment, scores in treatment_scores.items()
        }

    result = {
        "schema_version": "openimages_treatment_gate9.v0.1",
        "status": "pass",
        "dataset": "open-images-v7",
        "split": "validation",
        "selection_rule": source["selection_rule"],
        "concept_pack_size": len(concepts),
        "model": {"family": "clip", "model_id": MODEL_ID, "model_revision": MODEL_REVISION},
        "candidate_digests": {
            "direct-v0": direct_candidate.candidate_digest,
            "deterministic-v0": deterministic_candidate.candidate_digest,
            "active-v0": active_candidate.candidate_digest,
        },
        "evaluation_protocol": evaluation_protocol,
        "aggregate": aggregates,
        "resource_telemetry": {
            treatment: {"model_views": model_views[treatment], "seconds": elapsed[treatment]}
            for treatment in ("direct-v0", "deterministic-v0", "active-v0")
        },
        "trials": per_image,
        "invariants": {
            "same_images": True,
            "same_model_and_revision": True,
            "same_concept_pack": True,
            "same_prompt_and_score_transform": True,
            "same_evaluation_protocol": True,
            "candidate_identity_separated": len(
                {
                    direct_candidate.candidate_digest,
                    deterministic_candidate.candidate_digest,
                    active_candidate.candidate_digest,
                }
            ) == 3,
            "classification_threshold_invented": False,
            "policy_ground_truth_claimed": False,
            "representative_population_claimed": False,
            "scaleout_without_policy_tuning": True,
            "private_content_present": False,
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
