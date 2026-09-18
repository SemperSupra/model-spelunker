#!/usr/bin/env python3
"""Public-safe qualification for external benchmark scope/mapping semantics."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from external_presence_eval import (
    aggregate_presence_scores,
    load_mappings,
    score_presence_item,
)
from xm3600_adapter import (
    build_caption_ranking_trials,
    iter_xm3600_jsonl,
)


def main() -> int:
    mappings = load_mappings(
        [
            {
                "dataset": "open-images",
                "external_label_id": "/m/cat",
                "cpe_concept_id": "object.animal.cat",
                "mapping": "exact",
                "ground_truth_scope": "image_level_concept_presence",
            },
            {
                "dataset": "open-images",
                "external_label_id": "/m/dog",
                "cpe_concept_id": "object.animal.dog",
                "mapping": "exact",
                "ground_truth_scope": "image_level_concept_presence",
            },
            {
                "dataset": "open-images",
                "external_label_id": "/m/bird",
                "cpe_concept_id": "object.animal.bird",
                "mapping": "related",
                "ground_truth_scope": "image_level_concept_presence",
            },
        ]
    )
    item = {
        "dataset": "open-images",
        "image_id": "img1",
        "ground_truth_scope": "image_level_concept_presence",
        "verified_present": [
            {"external_label_id": "/m/cat"},
            {"external_label_id": "/m/bird"},
        ],
        "verified_absent": [{"external_label_id": "/m/dog"}],
    }
    observations = [
        {
            "concept_id": "object.animal.cat",
            "label": "cat",
            "assertion": "candidate",
        },
        {
            "concept_id": "object.vehicle.car",
            "label": "car",
            "assertion": "candidate",
        },
    ]
    scored = score_presence_item(item=item, observations=observations, mappings=mappings)
    aggregate = aggregate_presence_scores([scored])
    if scored["counts"] != {"tp": 1, "fp": 0, "tn": 1, "fn": 0}:
        raise SystemExit(f"unexpected exact-scope counts: {scored['counts']}")
    if scored["excluded"] != [
        {
            "external_label_id": "/m/bird",
            "reason": "mapping_related",
            "assertion": "present",
            "cpe_concept_id": "object.animal.bird",
        }
    ]:
        raise SystemExit(f"non-exact mapping was not retained correctly: {scored['excluded']}")
    if aggregate["precision"] != 1.0 or aggregate["recall"] != 1.0 or aggregate["specificity"] != 1.0:
        raise SystemExit("unexpected scoped aggregate metrics")

    with TemporaryDirectory(prefix="xm3600-adapter-") as tmp:
        path = Path(tmp) / "captions.jsonl"
        path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "image_id": "i1",
                            "captions": {
                                "en": ["a red car"],
                                "th": ["รถสีแดง"],
                            },
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "image_id": "i2",
                            "language": "en",
                            "captions": ["a blue boat"],
                        }
                    ),
                    json.dumps(
                        {
                            "image_id": "i2",
                            "language": "th",
                            "caption": "เรือสีน้ำเงิน",
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "image_id": "i3",
                            "captions": {
                                "en": ["a green tree"],
                                "th": ["ต้นไม้สีเขียว"],
                            },
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "image_id": "i4",
                            "captions": {
                                "en": ["a white house"],
                                "th": ["บ้านสีขาว"],
                            },
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        captions = list(iter_xm3600_jsonl(path))
        trials = build_caption_ranking_trials(
            captions,
            languages=["en", "th"],
            decoys_per_trial=2,
        )

    if len(captions) != 8:
        raise SystemExit(f"expected 8 normalized captions, got {len(captions)}")
    if not trials:
        raise SystemExit("expected multilingual ranking trials")
    languages = sorted({x["language"] for x in trials})
    if languages != ["en", "th"]:
        raise SystemExit(f"unexpected trial languages: {languages}")
    if any(
        decoy["image_id"] == trial["image_id"]
        for trial in trials
        for decoy in trial["decoy_captions"]
    ):
        raise SystemExit("XM3600 decoy must come from a different image")

    result = {
        "schema_version": "external_visual_benchmark_ringer.v0.1",
        "status": "pass",
        "open_images_scope": {
            "counts": scored["counts"],
            "excluded_non_exact": len(scored["excluded"]),
            "precision": aggregate["precision"],
            "recall": aggregate["recall"],
            "specificity": aggregate["specificity"],
        },
        "xm3600": {
            "captions_normalized": len(captions),
            "ranking_trials": len(trials),
            "languages": languages,
        },
        "invariants": {
            "unannotated_not_scored_as_absent": True,
            "non_exact_mapping_not_scored": True,
            "external_ground_truth_scope_explicit": True,
            "policy_ground_truth_claimed": False,
            "multilingual_caption_alignment_preserved": True,
            "private_content_present": False,
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
