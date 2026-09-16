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
TRACR_REPO = "google-deepmind/tracr"
TRACR_REVISION = "9ce2b8c82b6ba10e62e86cf6f390e7536d4fd2cd"
PROGRAMS = {"reverse", "hist"}


def finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def sha256_json(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def validate_tensor(s: dict) -> None:
    assert isinstance(s["shape"], list) and s["shape"]
    assert isinstance(s["dtype"], str) and s["dtype"]
    assert s["sha256"].startswith("sha256:") and len(s["sha256"]) == 71
    for key in ("l2", "mean", "std", "min", "max"):
        assert finite(s[key])
    assert s["l2"] >= 0 and s["std"] >= 0 and s["min"] <= s["max"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    args = p.parse_args()
    b = json.loads(args.bundle.read_text(encoding="utf-8"))
    jsonschema.validate(b, json.loads(SCHEMA.read_text(encoding="utf-8")))

    assert b["probe_id"] == "c1-tracr-oracle-calibration-v1"
    assert b["instrument"] == "compiled-transformer-ground-truth-oracle-suite"
    assert b["access_tier"] == "A2"
    assert b["evidence_level"] == "REPRODUCED"

    model = b["model_identity"]
    assert model["repository"] == TRACR_REPO
    assert model["revision"] == TRACR_REVISION
    assert model["model_class"] == "compiled-routine-transformers"
    assert set(model["parameter_digests"]) == PROGRAMS
    assert all(x.startswith("sha256:") and len(x) == 71 for x in model["parameter_digests"].values())

    ap = b["artifact_provenance"]
    assert ap["tracked"] is False
    assert "compiled" in ap["reason"].lower() and "sha-256" in ap["reason"].lower()

    obs = b["observations"]
    source = obs["source"]
    assert source == {
        "repository": TRACR_REPO,
        "exact_revision": TRACR_REVISION,
        "license": "Apache-2.0",
        "archived_read_only_specimen": True,
    }
    protocol = obs["protocol"]
    assert protocol["programs"] == ["reverse", "hist"]
    assert protocol["max_seq_len"] == 5
    assert protocol["bos"] == "BOS" and protocol["pad"] == "PAD"
    assert protocol["causal"] is False
    assert protocol["raw_tensor_persistence"] is False

    programs = obs["programs"]
    assert len(programs) == 2 and {p["program_id"] for p in programs} == PROGRAMS
    total_cases = 0
    for program in programs:
        pid = program["program_id"]
        assert program["program_spec_hash"].startswith("sha256:") and len(program["program_spec_hash"]) == 71
        assert program["parameter_sha256"] == model["parameter_digests"][pid]
        assert program["repeat_parameter_sha256"] == program["parameter_sha256"]
        assert program["parameter_repeat_exact"] is True
        assert int(program["parameter_count"]) > 0
        assert program["parameter_leaves"]
        assert all(x["sha256"].startswith("sha256:") and len(x["sha256"]) == 71 for x in program["parameter_leaves"])

        cfg = program["model_config"]
        assert int(cfg["num_layers"]) >= 1
        assert int(cfg["num_heads"]) >= 1
        assert int(cfg["key_size"]) >= 1
        assert int(cfg["mlp_hidden_size"]) >= 1
        assert cfg["causal"] is False

        labels = program["residual_labels"]
        assert labels and len(labels) >= 2
        label_map = program["oracle_label_indices"]
        assert pid in label_map and len(label_map[pid]) > 0
        for name, indices in label_map.items():
            assert isinstance(name, str) and name
            assert isinstance(indices, list)
            assert all(isinstance(i, int) and 0 <= i < len(labels) for i in indices)
        assert program["oracle_label_coverage"][pid] == len(label_map[pid])

        cases = program["cases"]
        assert len(cases) == 3
        total_cases += len(cases)
        for c in cases:
            assert c["behavior_correct"] is True
            assert c["repeat_decoded_equal"] is True
            assert c["decoded"] == c["expected"]
            assert len(c["input_tokens"]) == 5
            validate_tensor(c["transformer_output"])
            validate_tensor(c["input_embeddings"])
            assert len(c["residuals"]) == 2 * cfg["num_layers"]
            assert len(c["layer_outputs"]) == 2 * cfg["num_layers"]
            assert len(c["attention_logits"]) == cfg["num_layers"]
            for s in c["residuals"] + c["layer_outputs"]:
                validate_tensor(s)
            for attn in c["attention_logits"]:
                validate_tensor(attn)
                assert attn["layout"] in {"BHQK", "BQKH"}
                assert len(attn["heads"]) == cfg["num_heads"]
                for head in attn["heads"]:
                    assert len(head["argmax_key_by_query"]) == 5
                    assert finite(head["mean_attention_entropy"]) and head["mean_attention_entropy"] >= 0
                    assert len(head["max_probability_by_query"]) == 5
                    assert all(finite(x) and 0 <= x <= 1.000001 for x in head["max_probability_by_query"])
            energies = c["oracle_subspace_energy_fraction_by_residual"]
            assert set(energies) == set(label_map)
            for name, values in energies.items():
                assert len(values) == len(c["residuals"])
                if label_map[name]:
                    assert all(finite(x) and -1e-8 <= x <= 1.000001 for x in values)
                else:
                    assert all(x is None for x in values)

    d = b["derived_metrics"]
    assert d["all_behavior_correct"] is True
    assert d["all_apply_repeats_exact"] is True
    assert d["all_parameter_repeats_exact"] is True
    assert d["oracle_surfaces_present"] is True
    assert d["ground_truth_output_labels_found"] is True
    assert d["program_count"] == 2 and d["case_count"] == total_cases == 6
    checks = d["portable_method_checks"]
    assert checks and all(v is True for v in checks.values())

    expected_hash = sha256_json({"observations": obs, "derived_metrics": d})
    assert b["provenance"]["raw_output_hash"] == expected_hash
    assert b["provenance"]["model_revision"] == TRACR_REVISION

    print(json.dumps({
        "valid": True,
        "probe_id": b["probe_id"],
        "tracr_revision": TRACR_REVISION,
        "programs": {p["program_id"]: {"layers": p["model_config"]["num_layers"], "heads": p["model_config"]["num_heads"], "params": p["parameter_count"], "residual_dims": len(p["residual_labels"])} for p in programs},
        "cases": total_cases,
        "compiled_parameters_repeat_exact": True,
        "scientific_outcome_not_acceptance_gate": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
