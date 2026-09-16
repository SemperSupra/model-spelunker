#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "observation-bundle.schema.json"
LOGICAL_ID = "rerank/cross-encoder/ms-marco-minilm-l6-v2"
UPSTREAM_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"


def sha256_json(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def validate_path(path: list[dict], threshold: float, *, required: set[str] | None = None) -> None:
    assert path
    assert path[0]["step"] == 0
    previous_words = path[0]["word_count"]
    for i, row in enumerate(path):
        assert row["step"] == i
        assert isinstance(row["text"], str) and row["text"]
        assert isinstance(row["word_count"], int) and row["word_count"] >= 1
        assert finite(row["score"])
        assert row["score"] >= threshold - 1e-6
        if i > 0:
            assert row["word_count"] == previous_words - 1
            assert row["removed"] is not None
        previous_words = row["word_count"]
        if required:
            normalized = {w.strip(".,;:!?\"'").lower() for w in row["text"].split()}
            assert required.issubset(normalized)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    args = p.parse_args()

    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    jsonschema.validate(bundle, json.loads(SCHEMA.read_text(encoding="utf-8")))

    assert bundle["probe_id"] == "reranker-counterexample-minimization-v1"
    assert bundle["instrument"] == "counterexample-minimize-and-representation-contrast"
    assert bundle["access_tier"] == "A2"
    assert bundle["evidence_level"] == "REPRODUCED"

    model = bundle["model_identity"]
    assert model["logical_id"] == LOGICAL_ID
    assert model["revision"] == UPSTREAM_REVISION
    assert model["foundry_state"] == "candidate"

    ap = bundle["artifact_provenance"]
    assert ap["tracked"] is True
    assert ap["logical_artifact_id"] == LOGICAL_ID
    assert ap["upstream_revision"] == UPSTREAM_REVISION
    assert ap["identity_kind"] == "oci"
    assert ap["identity_digest"].startswith("sha256:") and len(ap["identity_digest"]) == 71
    assert ap["verified"] is True
    assert ap["foundry_record_ref"]

    obs = bundle["observations"]
    assert obs["artifact_state"] == "candidate"
    assert obs["query"] == "Which planet is the largest in the Solar System?"
    assert obs["reference"]["text"] == "Jupiter is the largest planet in the Solar System."
    assert finite(obs["reference"]["score"])
    assert finite(obs["near_tie_tolerance"]) and obs["near_tie_tolerance"] > 0
    assert finite(obs["near_tie_threshold"])
    assert abs(obs["near_tie_threshold"] - (obs["reference"]["score"] - obs["near_tie_tolerance"])) <= 1e-6

    curated = obs["curated_variants"]
    assert len(curated) == 9
    assert curated[0]["id"] == "seed_false"
    for row in curated:
        assert isinstance(row["id"], str) and row["id"]
        assert isinstance(row["text"], str) and row["text"]
        assert finite(row["score"])
        assert finite(row["score_gap_from_reference"])
        assert isinstance(row["near_tie_within_tolerance"], bool)
        assert isinstance(row["token_count"], int) and row["token_count"] > 0
        expected_near = row["score"] >= obs["near_tie_threshold"]
        assert row["near_tie_within_tolerance"] == expected_near

    unconstrained = obs["unconstrained_greedy_minimization"]
    constrained = obs["false_semantics_preserving_greedy_minimization"]
    assert constrained["required_terms"] == ["mars", "largest", "planet"]
    validate_path(unconstrained, obs["near_tie_threshold"])
    validate_path(constrained["path"], obs["near_tie_threshold"], required={"mars", "largest", "planet"})

    layers = obs["layerwise_reference_cls_distances"]
    assert len(layers) == 7
    ids = {row["id"] for row in curated}
    for i, row in enumerate(layers):
        assert row["layer"] == i
        assert set(row["distances"]) == ids
        assert all(finite(v) and v >= -1e-6 for v in row["distances"].values())

    derived = bundle["derived_metrics"]
    assert finite(derived["repeat_max_abs_delta"]) and derived["repeat_max_abs_delta"] <= 1e-6
    assert isinstance(derived["curated_near_tie_ids"], list)
    assert derived["unconstrained_final"] == unconstrained[-1]
    assert derived["constrained_final"] == constrained["path"][-1]
    corr = derived["final_layer_score_gap_vs_cls_distance_pearson"]
    assert corr is None or finite(corr)
    checks = derived["portable_method_checks"]
    assert checks and all(v is True for v in checks.values())

    expected_hash = sha256_json({"observations": obs, "derived_metrics": derived})
    assert bundle["provenance"]["raw_output_hash"] == expected_hash

    print(json.dumps({
        "valid": True,
        "probe_id": bundle["probe_id"],
        "identity_digest": ap["identity_digest"],
        "curated_near_tie_ids": derived["curated_near_tie_ids"],
        "unconstrained_final": derived["unconstrained_final"],
        "constrained_final": derived["constrained_final"],
        "semantic_outcome_not_acceptance_gate": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
