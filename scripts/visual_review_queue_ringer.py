#!/usr/bin/env python3
"""Public-safe Gate-5 qualification for review-queue semantics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from visual_review_queue import build_review_queue, load_batch_manifest


def obs(concept_id: str, kind: str = "visual_model_score") -> dict:
    return {
        "observation_id": f"obs-{concept_id}",
        "concept_id": concept_id,
        "label": concept_id,
        "assertion": "candidate",
        "evidence": [{"kind": kind, "source": "synthetic"}],
        "counter_evidence": [],
        "parent_observation_id": None,
    }


def write_batch(root: Path, name: str, candidate: str, treatment: str, per_asset: dict) -> Path:
    d = root / name
    d.mkdir()
    rows = []
    for asset_id, observations in per_asset.items():
        p = d / f"{asset_id}.json"
        input_sha = hashlib.sha256(asset_id.encode()).hexdigest()
        payload = {
            "input": {"sha256": input_sha},
            "observations": observations,
            "run_digest": hashlib.sha256((name + asset_id).encode()).hexdigest(),
        }
        p.write_text(json.dumps(payload), encoding="utf-8")
        rows.append(
            {
                "asset_id": asset_id,
                "input_sha256": input_sha,
                "result_digest": payload["run_digest"],
                "output_file": p.name,
            }
        )
    m = d / "manifest.json"
    m.write_text(
        json.dumps(
            {
                "candidate_digest": candidate,
                "treatment": treatment,
                "results": rows,
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    return m


def main() -> int:
    benchmark = {
        "benchmark_id": "public-review-fixture",
        "benchmark_version": "v1",
        "assets": [
            {
                "asset": {
                    "benchmark_asset_id": "asset-a",
                    "source_filename": "a.jpg",
                    "sha256": hashlib.sha256(b"a").hexdigest(),
                },
                "concept_observations": [
                    {
                        "concept_id": "cat",
                        "assertion_state": "supported",
                        "status": "seed",
                    }
                ],
                "policy_probes": ["false_positive_guard"],
            },
            {
                "asset": {
                    "benchmark_asset_id": "asset-b",
                    "source_filename": "b.jpg",
                    "sha256": hashlib.sha256(b"b").hexdigest(),
                },
                "concept_observations": [],
                "policy_probes": [],
            },
        ],
    }

    with TemporaryDirectory(prefix="vcw-review-gate5-") as tmpdir:
        root = Path(tmpdir)
        m1 = write_batch(
            root,
            "direct",
            "1" * 64,
            "direct-v0",
            {"asset-a": [obs("cat")], "asset-b": [obs("tree")]},
        )
        m2 = write_batch(
            root,
            "active",
            "2" * 64,
            "active-v0",
            {"asset-a": [obs("dog")], "asset-b": [obs("tree"), obs("road")]},
        )
        first = build_review_queue(
            benchmark=benchmark,
            batches=[load_batch_manifest(m1), load_batch_manifest(m2)],
        )
        second = build_review_queue(
            benchmark=benchmark,
            batches=[load_batch_manifest(m1), load_batch_manifest(m2)],
        )

    if first["queue_digest"] != second["queue_digest"]:
        raise SystemExit("review queue digest is not reproducible")

    a = next(x for x in first["items"] if x["asset_id"] == "asset-a")
    b = next(x for x in first["items"] if x["asset_id"] == "asset-b")

    if a["seed_reference"]["authority"] != "seed_not_ground_truth":
        raise SystemExit("seed authority invariant violated")
    if a["comparison"]["auto_novel_vs_seed_reference"] != ["dog"]:
        raise SystemExit("novel-vs-seed cue is incorrect")
    if a["comparison"]["seed_reference_not_observed_by_auto"]:
        raise SystemExit("seed concept observed by one candidate must not be reported missing from all auto evidence")
    if {x["concept_key"] for x in a["comparison"]["cross_candidate_disagreements"]} != {"cat", "dog"}:
        raise SystemExit("cross-candidate disagreement set is incorrect")
    if b["comparison"]["auto_novel_vs_seed_reference"] != ["road", "tree"]:
        raise SystemExit("seed-empty auto novelty cue is incorrect")
    if first["safeguards"]["accuracy_metrics_present"] is not False:
        raise SystemExit("review queue must not manufacture accuracy metrics")
    if first["safeguards"]["not_observed_means_absent"] is not False:
        raise SystemExit("not-observed/absent distinction violated")

    result = {
        "schema_version": "visual_concept_review_gate5.v0.1",
        "status": "pass",
        "queue_digest": first["queue_digest"],
        "summary": first["summary"],
        "invariants": {
            "seed_not_ground_truth": True,
            "auto_not_ground_truth": True,
            "not_observed_not_absent": True,
            "cross_candidate_disagreement_retained": True,
            "auto_novel_vs_seed_is_review_cue_only": True,
            "queue_digest_reproducible": True,
            "private_content_present": False,
            "performance_claim": False,
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
