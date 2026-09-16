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
UPSTREAM_REPO = "cross-encoder/ms-marco-MiniLM-L6-v2"
UPSTREAM_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"


def sha256_json(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    args = p.parse_args()

    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(bundle, schema)

    assert bundle["probe_id"] == "reranker-portability-minilm-v1"
    assert bundle["instrument"] == "scalar-reranker-and-layer-geometry-suite"
    assert bundle["access_tier"] == "A2"
    assert bundle["evidence_level"] == "REPRODUCED"

    model = bundle["model_identity"]
    assert model["logical_id"] == LOGICAL_ID
    assert model["repository"] == UPSTREAM_REPO
    assert model["revision"] == UPSTREAM_REVISION
    assert model["model_class"] == "cross-encoder-reranker-scalar-judge"
    assert model["foundry_state"] == "candidate"

    provenance = bundle["artifact_provenance"]
    assert provenance["tracked"] is True
    assert provenance["logical_artifact_id"] == LOGICAL_ID
    assert provenance["upstream_repository"] == UPSTREAM_REPO
    assert provenance["upstream_revision"] == UPSTREAM_REVISION
    assert provenance["identity_kind"] == "oci"
    assert provenance["identity_digest"].startswith("sha256:") and len(provenance["identity_digest"]) == 71
    assert provenance["verified"] is True
    assert provenance["foundry_record_ref"]

    observations = bundle["observations"]
    assert observations["artifact_state"] == "candidate"
    families = observations["probe_families"]
    assert len(families) == 2
    expected_ids = {"red-planet", "largest-planet"}
    assert {row["family_id"] for row in families} == expected_ids

    for row in families:
        passages = row["passages"]
        assert len(passages) == 5
        assert {p["id"] for p in passages} == {"relevant_direct", "relevant_paraphrase", "lexical_distractor", "negated", "irrelevant"}
        assert [p["role"] for p in passages].count("relevant") == 2
        for field in ("direct_scores", "paraphrase_scores"):
            values = row[field]
            assert len(values) == 5
            assert all(finite(v) for v in values)
        assert len(row["direct_token_counts"]) == 5 and all(int(x) > 0 for x in row["direct_token_counts"])
        assert len(row["paraphrase_token_counts"]) == 5 and all(int(x) > 0 for x in row["paraphrase_token_counts"])
        assert finite(row["direct_best_relevant_margin"])
        assert finite(row["paraphrase_best_relevant_margin"])
        assert finite(row["direct_relevant_vs_negated_delta"])
        assert row["direct_vs_paraphrase_score_pearson"] is None or finite(row["direct_vs_paraphrase_score_pearson"])
        assert finite(row["repeat_max_abs_delta"]) and float(row["repeat_max_abs_delta"]) <= 1e-6
        order = row["input_order"]
        assert all(finite(order[k]) for k in ("forward_query_passage_score", "swapped_passage_query_score", "forward_minus_swapped"))
        layers = row["layer_cls_geometry"]
        assert len(layers) >= 2
        for layer in layers:
            assert isinstance(layer["layer"], int) and layer["layer"] >= 0
            assert finite(layer["mean_cls_l2"])
            distance_keys = [k for k in layer if k.endswith("_cosine_distance")]
            assert len(distance_keys) == 4
            assert all(finite(layer[k]) for k in distance_keys)

    derived = bundle["derived_metrics"]
    assert finite(derived["max_repeat_abs_delta"]) and float(derived["max_repeat_abs_delta"]) <= 1e-6
    assert len(derived["hidden_state_layer_counts"]) == 2
    assert all(int(x) >= 2 for x in derived["hidden_state_layer_counts"])
    checks = derived["portable_instrument_checks"]
    assert checks and all(value is True for value in checks.values())

    expected_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    assert bundle["provenance"]["raw_output_hash"] == expected_hash

    print(json.dumps({
        "valid": True,
        "probe_id": bundle["probe_id"],
        "identity_digest": provenance["identity_digest"],
        "foundry_state": model["foundry_state"],
        "semantic_ranking_not_required_for_acceptance": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
