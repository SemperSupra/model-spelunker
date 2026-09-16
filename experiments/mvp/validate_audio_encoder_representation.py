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
LOGICAL_ID = "asr/faster-whisper/tiny"
UPSTREAM_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
EXPECTED_DIGEST = "sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
FIXTURE_SHA = "sha256:63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715"
VARIANT_IDS = {"baseline", "quiet_x0_25", "prepend_silence_500ms", "noise_20db", "silence_control", "tone_440hz_control"}


def sha256_json(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    args = p.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    jsonschema.validate(bundle, json.loads(SCHEMA.read_text(encoding="utf-8")))

    assert bundle["probe_id"] == "audio-encoder-representation-faster-whisper-tiny-v1"
    assert bundle["instrument"] == "audio-logmel-encoder-representation-geometry-suite"
    assert bundle["access_tier"] == "A2"
    assert bundle["evidence_level"] == "REPRODUCED"

    model = bundle["model_identity"]
    assert model["logical_id"] == LOGICAL_ID
    assert model["revision"] == UPSTREAM_REVISION
    assert model["model_class"] == "speech-to-text-asr-encoder-decoder"

    ap = bundle["artifact_provenance"]
    assert ap["tracked"] is True
    assert ap["logical_artifact_id"] == LOGICAL_ID
    assert ap["upstream_revision"] == UPSTREAM_REVISION
    assert ap["identity_kind"] == "oci"
    assert ap["identity_digest"] == EXPECTED_DIGEST
    assert ap["verified"] is True

    obs = bundle["observations"]
    assert obs["fixture"]["sha256"] == FIXTURE_SHA
    protocol = obs["protocol"]
    assert protocol["faster_whisper_version"] == "1.2.1"
    assert protocol["pad_or_trim_frames"] == 3000
    assert protocol["full_encoder_tensor_persisted"] is False

    rows = obs["variants"]
    assert len(rows) == 6
    assert {row["id"] for row in rows} == VARIANT_IDS
    encoder_shapes = []
    for row in rows:
        audio = row["audio"]
        assert audio["sample_rate"] == 16000
        assert int(audio["samples"]) > 0
        assert finite(audio["duration_seconds"]) and audio["duration_seconds"] > 0
        assert finite(audio["rms"]) and audio["rms"] >= 0
        assert audio["sha256_float32le"].startswith("sha256:") and len(audio["sha256_float32le"]) == 71

        rep = row["representation"]
        unpadded = rep["feature_shape_unpadded"]
        assert len(unpadded) == 2 and unpadded[0] == 80 and unpadded[1] > 0
        assert rep["feature_frames_used"] > 0 and rep["feature_frames_used"] <= 3000
        assert rep["feature_shape_encoder_input"] == [80, 3000]
        assert rep["feature_sha256_float32"].startswith("sha256:") and len(rep["feature_sha256_float32"]) == 71
        assert finite(rep["feature_mean"]) and finite(rep["feature_std"])

        shape = rep["encoder_shape"]
        assert len(shape) == 3 and shape[0] == 1 and shape[1] > 0 and shape[2] > 0
        encoder_shapes.append(shape)
        assert rep["encoder_dtype"] == "float32"
        assert rep["encoder_sha256_float32"].startswith("sha256:") and len(rep["encoder_sha256_float32"]) == 71
        assert finite(rep["encoder_output_frames_per_input_frame"]) and rep["encoder_output_frames_per_input_frame"] > 0
        assert 1 <= rep["active_encoder_frames_inferred"] <= shape[1]
        assert finite(rep["active_pooled_l2"]) and rep["active_pooled_l2"] >= 0
        assert finite(rep["active_pooled_mean"]) and finite(rep["active_pooled_std"])
        qs = rep["active_frame_l2_quantiles"]
        assert set(qs) == {"min", "q25", "median", "q75", "max"}
        assert all(finite(v) and v >= 0 for v in qs.values())
        assert qs["min"] <= qs["q25"] <= qs["median"] <= qs["q75"] <= qs["max"]

        geom = row["geometry_from_baseline"]
        assert int(geom["common_active_frames"]) > 0
        for key in ("active_mean_pooled_cosine_distance", "mean_frame_cosine_distance", "median_frame_cosine_distance", "mean_frame_l2_difference", "relative_frobenius_difference"):
            assert finite(geom[key])
            assert geom[key] >= -1e-6

    assert len({tuple(x) for x in encoder_shapes}) == 1
    baseline = next(row for row in rows if row["id"] == "baseline")
    bg = baseline["geometry_from_baseline"]
    assert abs(bg["active_mean_pooled_cosine_distance"]) <= 1e-6
    assert abs(bg["mean_frame_cosine_distance"]) <= 1e-6
    assert abs(bg["relative_frobenius_difference"]) <= 1e-6

    repeat = obs["baseline_repeat"]
    assert repeat["encoder_hash_equal"] is True
    assert repeat["representation"]["encoder_shape"] == baseline["representation"]["encoder_shape"]
    assert finite(repeat["pooled_cosine_distance"]) and abs(repeat["pooled_cosine_distance"]) <= 1e-6
    for key in ("mean_frame_cosine_distance", "median_frame_cosine_distance", "mean_frame_l2_difference", "relative_frobenius_difference"):
        assert finite(repeat["aligned_metrics"][key])
        assert abs(repeat["aligned_metrics"][key]) <= 1e-6

    derived = bundle["derived_metrics"]
    for field in ("pooled_cosine_distance_from_baseline", "mean_aligned_frame_cosine_distance_from_baseline", "relative_frobenius_difference_from_baseline"):
        assert set(derived[field]) == VARIANT_IDS
        assert all(finite(v) and v >= -1e-6 for v in derived[field].values())
    assert derived["baseline_repeat_encoder_hash_equal"] is True
    assert finite(derived["baseline_repeat_pooled_cosine_distance"])
    assert finite(derived["baseline_repeat_mean_frame_cosine_distance"])
    checks = derived["portable_instrument_checks"]
    assert checks and all(v is True for v in checks.values())

    expected_hash = sha256_json({"observations": obs, "derived_metrics": derived})
    assert bundle["provenance"]["raw_output_hash"] == expected_hash

    print(json.dumps({
        "valid": True,
        "probe_id": bundle["probe_id"],
        "identity_digest": ap["identity_digest"],
        "encoder_shape": baseline["representation"]["encoder_shape"],
        "pooled_distances": derived["pooled_cosine_distance_from_baseline"],
        "full_tensor_persisted": protocol["full_encoder_tensor_persisted"],
        "scientific_outcome_not_acceptance_gate": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
