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
TRACR_REVISION = "9ce2b8c82b6ba10e62e86cf6f390e7536d4fd2cd"
EXPECTED_IDS = {"identity", "cycle_content_plus1", "swap_content_1_2", "collapse_content_position_codes"}
EXPECTED_ROUTES = {
    "identity": [0, 4, 3, 2, 1],
    "cycle_content_plus1": [0, 2, 1, 4, 3],
    "swap_content_1_2": [0, 3, 4, 1, 2],
}


def finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def sha256_json(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def check_route_rows(rows) -> None:
    assert len(rows) == 2
    assert {r["layer"] for r in rows} == {0, 1}
    for r in rows:
        for key in ("mean_target_route_probability_content", "target_route_argmax_fraction_content", "mean_content_attention_entropy"):
            assert finite(r[key])
        assert 0.0 <= r["mean_target_route_probability_content"] <= 1.0 + 1e-6
        assert 0.0 <= r["target_route_argmax_fraction_content"] <= 1.0 + 1e-6
        mat = r["mean_attention_matrix"]
        assert len(mat) == 5 and all(len(x) == 5 for x in mat)
        assert all(finite(x) for row in mat for x in row)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    args = p.parse_args()
    b = json.loads(args.bundle.read_text(encoding="utf-8"))
    jsonschema.validate(b, json.loads(SCHEMA.read_text(encoding="utf-8")))

    assert b["probe_id"] == "c1-learned-reverse-position-code-falsifier-v1"
    assert b["instrument"] == "targeted-position-code-causal-routing-suite"
    assert b["access_tier"] == "A4"
    assert b["evidence_level"] == "CAUSAL"
    assert b["model_identity"]["revision"] == TRACR_REVISION
    assert b["model_identity"]["logical_id"] == "trained/tracr-transformer/reverse-seed0"
    assert b["artifact_provenance"]["tracked"] is False

    obs = b["observations"]
    specimen = obs["learned_specimen"]
    assert specimen["seed"] == 0
    assert specimen["training_steps"] == 1000
    assert specimen["position_table_shape"] == [5, 32]
    assert specimen["final_parameter_count"] > 0
    final_hash = specimen["final_parameter_sha256"]
    assert final_hash.startswith("sha256:") and len(final_hash) == 71
    assert specimen["baseline_test_accuracy"]["sequence_accuracy"] >= 0.99

    protocol = obs["causal_protocol"]
    assert protocol["original_reverse_route"] == [0, 4, 3, 2, 1]
    assert protocol["predeclared_route_prediction"] == "P^-1 o reverse o P"
    rows = protocol["interventions"]
    assert len(rows) == 4
    assert {x["id"] for x in rows} == EXPECTED_IDS
    by_id = {x["id"]: x for x in rows}

    for iid, expected in EXPECTED_ROUTES.items():
        row = by_id[iid]
        assert row["kind"] == "position_code_permutation"
        assert row["predeclared_predicted_route"] == expected
        ev = row["evaluation"]
        assert ev["predicted_route"] == expected
        assert ev["parameter_sha256"].startswith("sha256:") and len(ev["parameter_sha256"]) == 71
        for key in ("original_reverse_sequence_accuracy", "predicted_route_sequence_accuracy", "best_predicted_route_probability", "best_predicted_route_argmax_fraction", "best_original_route_probability", "best_original_route_argmax_fraction"):
            assert finite(ev[key])
        assert 0 <= ev["original_reverse_sequence_accuracy"] <= 1
        assert 0 <= ev["predicted_route_sequence_accuracy"] <= 1
        check_route_rows(ev["original_reverse_route"])
        check_route_rows(ev["predicted_route_attention"])

    identity = by_id["identity"]["evaluation"]
    assert identity["parameter_sha256"] == final_hash
    assert identity["original_reverse_sequence_accuracy"] >= 0.99
    assert identity["predicted_route_sequence_accuracy"] >= 0.99

    collapse = by_id["collapse_content_position_codes"]
    assert collapse["kind"] == "position_code_collapse_control"
    assert collapse["predeclared_predicted_route"] is None
    cev = collapse["evaluation"]
    assert finite(cev["original_reverse_sequence_accuracy"])
    assert finite(cev["best_original_route_probability"])
    check_route_rows(cev["original_reverse_route"])

    d = b["derived_metrics"]
    assert d["identity_parameter_hash_equal_to_baseline"] is True
    assert d["identity_original_reverse_sequence_accuracy"] >= 0.99
    assert len(d["structured_permutation_predicted_route_probability_exceeds_original_route"]) == 2
    assert all(isinstance(v, bool) for v in d["structured_permutation_predicted_route_probability_exceeds_original_route"])
    assert len(d["structured_permutation_predicted_route_sequence_accuracy"]) == 2
    assert all(finite(v) and 0 <= v <= 1 for v in d["structured_permutation_predicted_route_sequence_accuracy"])
    assert finite(d["mean_structured_predicted_route_sequence_accuracy"])
    assert finite(d["collapse_original_reverse_sequence_accuracy"])
    checks = d["portable_method_checks"]
    assert checks and all(v is True for v in checks.values())

    ctx = obs["cross_job_reproducibility_context"]
    assert set(ctx["prior_seed0_final_parameter_sha256"]) == {"rep34", "rep35"}
    assert ctx["current_seed0_final_parameter_sha256"] == final_hash

    expected_hash = sha256_json({"observations": obs, "derived_metrics": d})
    assert b["provenance"]["raw_output_hash"] == expected_hash

    print(json.dumps({
        "valid": True,
        "final_parameter_sha256": final_hash,
        "structured_prediction_flags": d["structured_permutation_predicted_route_probability_exceeds_original_route"],
        "structured_predicted_sequence_accuracy": d["structured_permutation_predicted_route_sequence_accuracy"],
        "collapse_reverse_sequence_accuracy": d["collapse_original_reverse_sequence_accuracy"],
        "scientific_outcome_not_acceptance_gate": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
