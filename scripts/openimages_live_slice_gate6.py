#!/usr/bin/env python3
"""Gate 6: real Open Images human-verified labels + real CLIP ranking evidence."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import urllib.request

import requests

from external_presence_eval import (
    aggregate_verified_rankings,
    load_mappings,
    score_verified_ranking,
)
from openimages_qualification import (
    group_qualification_items,
    iter_human_image_labels,
    load_class_descriptions,
)
from visual_concept_worker_core import CandidateSpec, canonical_digest, run_direct
from visual_concept_worker_ringer import PublicHFScorer


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8")


def select_label_groups(url: str, *, images: int, min_present: int, min_absent: int):
    selected = []
    with urllib.request.urlopen(url, timeout=60) as response:
        text = io.TextIOWrapper(response, encoding="utf-8", newline="")
        reader = csv.DictReader(text)
        required = {"ImageID", "Source", "LabelName", "Confidence"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise SystemExit(f"Open Images human-label schema drift: {reader.fieldnames}")

        current_id = None
        group = []

        def consider(rows):
            if not rows:
                return
            sources = {row["Source"].strip() for row in rows}
            if not sources.issubset({"verification", "crowdsource-verification"}):
                raise SystemExit(f"unexpected non-human source in human label file: {sources}")
            positives = sum(row["Confidence"].strip() == "1" for row in rows)
            negatives = sum(row["Confidence"].strip() == "0" for row in rows)
            invalid = [row["Confidence"] for row in rows if row["Confidence"].strip() not in {"0", "1"}]
            if invalid:
                raise SystemExit(f"unexpected confidence in human label file: {invalid[:3]}")
            if positives >= min_present and negatives >= min_absent:
                selected.append(list(rows))

        for row in reader:
            image_id = row["ImageID"]
            if current_id is None:
                current_id = image_id
            if image_id != current_id:
                consider(group)
                if len(selected) >= images:
                    break
                current_id = image_id
                group = []
            group.append(row)
        if len(selected) < images:
            consider(group)

    if len(selected) < images:
        raise SystemExit(f"could not find {images} qualifying validation images")
    return selected[:images]


def main() -> int:
    source = json.loads(
        Path("data/external-benchmarks/openimages-v7-validation-source.json").read_text(
            encoding="utf-8"
        )
    )
    rule = source["selection_rule"]
    class_text = fetch_text(source["class_descriptions_url"])
    selected_groups = select_label_groups(
        source["human_labels_url"],
        images=int(rule["images"]),
        min_present=int(rule["verified_present_per_image"]),
        min_absent=int(rule["verified_absent_per_image"]),
    )

    with TemporaryDirectory(prefix="openimages-gate6-") as tmpdir:
        root = Path(tmpdir)
        classes_path = root / "classes.csv"
        labels_path = root / "selected-labels.csv"
        classes_path.write_text(class_text, encoding="utf-8")
        with labels_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["ImageID", "Source", "LabelName", "Confidence"],
            )
            writer.writeheader()
            for group in selected_groups:
                writer.writerows(group)

        descriptions = load_class_descriptions(classes_path)
        normalized = group_qualification_items(
            iter_human_image_labels(labels_path, descriptions)
        )

        trials = []
        all_selected_labels = {}
        for item in normalized:
            present = sorted(
                item["verified_present"],
                key=lambda x: x["external_label_id"],
            )[: int(rule["verified_present_per_image"])]
            absent = sorted(
                item["verified_absent"],
                key=lambda x: x["external_label_id"],
            )[: int(rule["verified_absent_per_image"])]
            if len(present) < int(rule["verified_present_per_image"]) or len(absent) < int(rule["verified_absent_per_image"]):
                raise SystemExit("normalized Open Images group no longer meets selection rule")
            trial = {
                "dataset": "open-images",
                "image_id": item["image_id"],
                "ground_truth_scope": source["ground_truth_scope"],
                "verified_present": present,
                "verified_absent": absent,
            }
            trials.append(trial)
            for label in present + absent:
                mid = label["external_label_id"]
                all_selected_labels[mid] = label["external_label"]

        concepts = [
            {
                "label": all_selected_labels[mid],
                "concept_id": f"openimages:{mid}",
            }
            for mid in sorted(all_selected_labels)
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
                for mid in sorted(all_selected_labels)
            ]
        )

        cfg = {
            "worker_framework": "visual-concept-worker",
            "framework_version": "0.1.0",
            "backend_family": "clip",
            "model_id": "openai/clip-vit-base-patch32",
            "model_revision": "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268",
            "action_policy": "direct-v0",
            "toolset": ["score_concepts"],
            "parameters": {
                "prompt_template": "a photo of a {}",
                "score_transform": "softmax",
                "text_padding": True,
                "top_k": len(concepts),
            },
        }
        candidate = CandidateSpec(
            worker_framework=cfg["worker_framework"],
            framework_version=cfg["framework_version"],
            backend_family=cfg["backend_family"],
            model_id=cfg["model_id"],
            model_revision=cfg["model_revision"],
            concept_pack_digest=canonical_digest(concepts),
            action_policy=cfg["action_policy"],
            toolset=tuple(cfg["toolset"]),
            parameters=dict(cfg["parameters"]),
        )
        scorer = PublicHFScorer(cfg)

        scored = []
        trial_summaries = []
        for trial in trials:
            image_url = source["image_url_template"].format(image_id=trial["image_id"])
            response = requests.get(image_url, timeout=60)
            response.raise_for_status()
            image_path = root / f"{trial['image_id']}.jpg"
            image_path.write_bytes(response.content)

            worker = run_direct(
                scorer=scorer,
                candidate=candidate,
                image_path=image_path,
                concepts=concepts,
                top_k=len(concepts),
                execution_lane="public-ringer",
            )
            ranking = score_verified_ranking(
                item=trial,
                observations=worker["observations"],
                mappings=mappings,
            )
            scored.append(ranking)
            trial_summaries.append(
                {
                    "image_id": trial["image_id"],
                    "input_sha256": worker["input"]["sha256"],
                    "verified_present": [
                        x["external_label"] for x in trial["verified_present"]
                    ],
                    "verified_absent": [
                        x["external_label"] for x in trial["verified_absent"]
                    ],
                    "pairwise_accuracy": ranking["pairwise"]["accuracy"],
                    "positive_at_k_rate": ranking["positive_at_k"]["rate"],
                    "mean_positive_rank": ranking["mean_positive_rank"],
                }
            )

    aggregate = aggregate_verified_rankings(scored)
    result = {
        "schema_version": "openimages_live_slice_gate6.v0.1",
        "status": "pass",
        "dataset": "open-images-v7",
        "split": "validation",
        "selection_rule": rule,
        "model": {
            "family": cfg["backend_family"],
            "model_id": cfg["model_id"],
            "model_revision": cfg["model_revision"],
            "candidate_digest": candidate.candidate_digest,
        },
        "concept_pack_size": len(concepts),
        "trials": trial_summaries,
        "aggregate": aggregate,
        "invariants": {
            "official_human_verified_labels_used": True,
            "positive_and_negative_labels_used": True,
            "unannotated_labels_not_scored": True,
            "classification_threshold_invented": False,
            "candidate_state_treated_as_supported": False,
            "image_bytes_persisted_or_uploaded": False,
            "private_content_present": False,
            "policy_ground_truth_claimed": False,
            "representative_population_claimed": False,
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
