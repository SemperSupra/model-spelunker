#!/usr/bin/env python3
"""Public-safe Gate-12 ringer for no-gold analysis and repeatability semantics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from visual_evidence_analysis import analyze_batches, compare_batch_sets, load_batch


def obs(concept_id: str, *, assertion: str = "candidate", kind: str = "visual_model_score") -> dict:
    return {
        "observation_id": f"obs-{concept_id}-{kind}",
        "concept_id": concept_id,
        "label": concept_id,
        "assertion": assertion,
        "evidence": [{"kind": kind, "source": "synthetic", "score": 0.5, "raw_score": 0.25}],
        "counter_evidence": [],
        "parent_observation_id": None,
    }


def write_batch(
    root: Path,
    name: str,
    candidate: str,
    treatment: str,
    per_asset: dict[str, list[dict]],
    *,
    digest_salt: str = "",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for asset_id, observations in per_asset.items():
        path = directory / f"{asset_id}.json"
        input_sha = hashlib.sha256(asset_id.encode()).hexdigest()
        payload = {
            "input": {"sha256": input_sha},
            "observations": observations,
            "run_digest": hashlib.sha256((name + asset_id + digest_salt).encode()).hexdigest(),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        rows.append(
            {
                "asset_id": asset_id,
                "input_sha256": input_sha,
                "result_digest": payload["run_digest"],
                "output_file": path.name,
            }
        )
    manifest = directory / "manifest.json"
    manifest.write_text(
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
    return manifest


def main() -> int:
    with TemporaryDirectory(prefix="visual-gate12-") as tmp:
        root = Path(tmp)

        direct_a = write_batch(
            root,
            "direct-a",
            "1" * 64,
            "direct-v0",
            {
                "asset-a": [obs("cat"), obs("dog")],
                "asset-b": [obs("tree")],
            },
        )
        deterministic_a = write_batch(
            root,
            "det-a",
            "2" * 64,
            "deterministic-v0",
            {
                "asset-a": [obs("cat"), obs("dog", kind="ocr_text")],
                "asset-b": [obs("tree"), obs("road")],
            },
        )
        active_a = write_batch(
            root,
            "active-a",
            "3" * 64,
            "active-v0",
            {
                "asset-a": [obs("cat")],
                "asset-b": [obs("tree")],
            },
        )

        analysis = analyze_batches(map(load_batch, [direct_a, deterministic_a, active_a]))
        assert analysis["safeguards"] == {
            "ground_truth_used": False,
            "accuracy_metrics_present": False,
            "candidate_ranking_present": False,
            "not_observed_means_absent": False,
            "seed_reference_used_for_scoring": False,
        }
        assert analysis["candidates"]["deterministic-v0:" + "2" * 12]["ocr_associated_assets"] == ["asset-a"]
        row_a = next(x for x in analysis["assets"] if x["asset_id"] == "asset-a")
        assert row_a["intersection_all_observed_candidates"] == ["cat"]
        assert row_a["disagreement_concepts"] == ["dog"]
        assert not row_a["semantic_duplicate_groups"]

        direct_b = write_batch(
            root,
            "direct-b",
            "1" * 64,
            "direct-v0",
            {
                "asset-a": [obs("cat"), obs("dog")],
                "asset-b": [obs("tree")],
            },
            digest_salt="same-semantics-new-identity",
        )
        deterministic_b = write_batch(
            root,
            "det-b",
            "2" * 64,
            "deterministic-v0",
            {
                "asset-a": [obs("cat"), obs("dog", kind="ocr_text")],
                "asset-b": [obs("tree"), obs("road")],
            },
            digest_salt="same-semantics-new-identity",
        )
        active_b = write_batch(
            root,
            "active-b",
            "3" * 64,
            "active-v0",
            {
                "asset-a": [obs("cat")],
                "asset-b": [obs("tree")],
            },
            digest_salt="same-semantics-new-identity",
        )
        try:
            compare_batch_sets(
                [load_batch(direct_a), load_batch(direct_a)],
                [load_batch(direct_b)],
            )
        except ValueError as exc:
            assert "duplicate batch key" in str(exc)
        else:
            raise AssertionError("duplicate comparator batch key must fail closed")

        semantic_stable = compare_batch_sets(
            map(load_batch, [direct_a, deterministic_a, active_a]),
            map(load_batch, [direct_b, deterministic_b, active_b]),
        )
        assert semantic_stable["repeatability_class"] == "semantic_stable_identity_drift"
        assert semantic_stable["summary"] == {"identity_drift_semantic_equal": 6}

        direct_c = write_batch(
            root,
            "direct-c",
            "1" * 64,
            "direct-v0",
            {
                "asset-a": [obs("cat"), obs("fox")],
                "asset-b": [obs("tree")],
            },
            digest_salt="semantic-change",
        )
        semantic_drift = compare_batch_sets(
            map(load_batch, [direct_a, deterministic_a, active_a]),
            map(load_batch, [direct_c, deterministic_b, active_b]),
        )
        assert semantic_drift["repeatability_class"] == "semantic_or_input_drift"
        assert semantic_drift["summary"]["semantic_drift"] == 1

        exact = compare_batch_sets(
            map(load_batch, [direct_a, deterministic_a, active_a]),
            map(load_batch, [direct_a, deterministic_a, active_a]),
        )
        assert exact["repeatability_class"] == "stable_identity"
        assert exact["summary"] == {"stable_identity_equal": 6}

        assert "accuracy" not in json.dumps(analysis["pairwise"]).lower()
        assert "winner" not in json.dumps(analysis["pairwise"]).lower()
        assert "ranking" not in json.dumps(analysis["pairwise"]).lower()

        print(
            json.dumps(
                {
                    "schema_version": "visual_gate12_evidence_analysis.v0.1",
                    "status": "pass",
                    "analysis_digest": analysis["analysis_digest"],
                    "repeatability_checks": {
                        "exact": exact["repeatability_class"],
                        "identity_drift": semantic_stable["repeatability_class"],
                        "semantic_drift": semantic_drift["repeatability_class"],
                    },
                    "private_content_present": False,
                    "ground_truth_used": False,
                    "candidate_ranking_present": False,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
