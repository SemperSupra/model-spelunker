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
GAIN = [0.5, 0.25, 0.125, 0.0625, 0.03125]
SNR = [40.0, 30.0, 20.0, 10.0, 5.0, 0.0]
SILENCE = [0.25, 0.5, 1.0, 2.0]


def finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def sha256_json(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    args = p.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    jsonschema.validate(bundle, json.loads(SCHEMA.read_text(encoding="utf-8")))

    assert bundle["probe_id"] == "audio-dose-response-faster-whisper-tiny-v1"
    assert bundle["instrument"] == "audio-feature-encoder-decoder-dose-response-suite"
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
    assert protocol["sample_rate"] == 16000
    assert protocol["encoder_feature_frames"] == 3000
    assert protocol["full_encoder_tensor_persisted"] is False
    assert protocol["families"] == ["gain", "snr_db", "leading_silence_seconds"]
    assert len(protocol["encoder_shape"]) == 3

    rows = obs["conditions"]
    assert len(rows) == 16
    assert sum(r["family"] == "baseline" for r in rows) == 1
    assert [float(r["level"]) for r in rows if r["family"] == "gain"] == GAIN
    assert [float(r["level"]) for r in rows if r["family"] == "snr_db"] == SNR
    assert [float(r["level"]) for r in rows if r["family"] == "leading_silence_seconds"] == SILENCE

    baseline = next(r for r in rows if r["family"] == "baseline")
    for row in rows:
        audio = row["audio"]
        assert int(audio["samples"]) > 0
        assert finite(audio["duration_seconds"]) and audio["duration_seconds"] > 0
        assert finite(audio["rms"]) and audio["rms"] >= 0
        assert audio["sha256_float32le"].startswith("sha256:") and len(audio["sha256_float32le"]) == 71

        feat = row["feature"]
        assert feat["feature_shape_unpadded"][0] == 80
        assert 1 <= feat["feature_frames_used"] <= 3000
        assert feat["feature_sha256_float32"].startswith("sha256:") and len(feat["feature_sha256_float32"]) == 71
        assert len(feat["encoder_shape"]) == 3 and feat["encoder_shape"][0] == 1
        assert feat["encoder_sha256_float32"].startswith("sha256:") and len(feat["encoder_sha256_float32"]) == 71
        for key in ("feature_mean", "feature_std", "encoder_output_frames_per_input_frame", "active_pooled_l2", "flattened_cosine_distance", "relative_frobenius_difference"):
            assert finite(feat[key])

        enc = row["encoder"]
        assert finite(enc["active_mean_pooled_cosine_distance_from_baseline"])
        for key in ("mean_cosine_distance", "median_cosine_distance", "relative_frobenius_difference"):
            assert finite(enc["unaligned"][key])
        if row["family"] == "leading_silence_seconds":
            shift = enc["shift_aware"]
            assert shift is not None
            assert int(shift["feature_offset_frames"]) > 0
            assert int(shift["encoder_offset_frames"]) > 0
            for surface in ("feature", "encoder"):
                assert int(shift[surface]["common_frames"]) > 0
                for key in ("mean_cosine_distance", "median_cosine_distance", "relative_frobenius_difference"):
                    assert finite(shift[surface][key])
        else:
            assert enc["shift_aware"] is None

        dec = row["decoder"]
        assert isinstance(dec["transcript"], str)
        assert isinstance(dec["segment_count"], int) and dec["segment_count"] >= 0
        td = dec["transcript_distance_from_baseline"]
        assert isinstance(td["word_edit_distance"], int) and td["word_edit_distance"] >= 0
        assert finite(td["normalized_word_edit_distance"])
        assert isinstance(dec["segment_count_changed"], bool)

    assert abs(baseline["feature"]["flattened_cosine_distance"]) <= 1e-6
    assert abs(baseline["feature"]["relative_frobenius_difference"]) <= 1e-6
    assert abs(baseline["encoder"]["active_mean_pooled_cosine_distance_from_baseline"]) <= 1e-6
    assert abs(baseline["encoder"]["unaligned"]["mean_cosine_distance"]) <= 1e-6
    assert baseline["decoder"]["transcript_distance_from_baseline"]["word_edit_distance"] == 0

    repeat = obs["baseline_repeat"]
    assert repeat["encoder_hash_equal"] is True
    assert repeat["transcript_equal"] is True
    assert repeat["transcript"] == obs["baseline"]["transcript"]

    derived = bundle["derived_metrics"]
    assert [float(x) for x in derived["family_levels"]["gain"]] == GAIN
    assert [float(x) for x in derived["family_levels"]["snr_db"]] == SNR
    assert [float(x) for x in derived["family_levels"]["leading_silence_seconds"]] == SILENCE
    assert derived["baseline_repeat_encoder_hash_equal"] is True
    assert derived["baseline_repeat_transcript_equal"] is True
    checks = derived["portable_method_checks"]
    assert checks and all(v is True for v in checks.values())

    # First-change fields are descriptive outcomes, not acceptance gates. If present,
    # however, they must point to an actually executed condition in the right family.
    by_id = {r["id"]: r for r in rows}
    for field, family in (
        ("first_gain_transcript_change", "gain"),
        ("first_snr_transcript_change_in_declared_order", "snr_db"),
        ("first_gain_segment_topology_change", "gain"),
        ("first_snr_segment_topology_change_in_declared_order", "snr_db"),
    ):
        value = derived[field]
        if value is not None:
            assert value["id"] in by_id
            assert by_id[value["id"]]["family"] == family
            assert float(value["level"]) == float(by_id[value["id"]]["level"])

    expected_hash = sha256_json({"observations": obs, "derived_metrics": derived})
    assert bundle["provenance"]["raw_output_hash"] == expected_hash

    print(json.dumps({
        "valid": True,
        "probe_id": bundle["probe_id"],
        "identity_digest": ap["identity_digest"],
        "conditions": len(rows),
        "first_gain_transcript_change": derived["first_gain_transcript_change"],
        "first_snr_transcript_change": derived["first_snr_transcript_change_in_declared_order"],
        "first_gain_segment_change": derived["first_gain_segment_topology_change"],
        "first_snr_segment_change": derived["first_snr_segment_topology_change_in_declared_order"],
        "scientific_outcome_not_acceptance_gate": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
