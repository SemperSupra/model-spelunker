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
DATASET_REPO = "PolyAI/minds14"
DATASET_REVISION = "40ce77cb32a384e4d50a568e1ec39ac804019d33"
EXPECTED_CONFIGS = {"de-DE": "de", "en-US": "en", "fr-FR": "fr"}
EXPECTED_INTENTS = {1, 12}
EXPECTED_CONDITIONS = {"baseline", "noise_20db", "noise_10db"}


def finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def sha256_json(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    args = p.parse_args()
    b = json.loads(args.bundle.read_text(encoding="utf-8"))
    jsonschema.validate(b, json.loads(SCHEMA.read_text(encoding="utf-8")))

    assert b["probe_id"] == "audio-multilingual-generalization-faster-whisper-tiny-v1"
    assert b["instrument"] == "multilingual-audio-feature-encoder-decoder-generalization-suite"
    assert b["access_tier"] == "A2"
    assert b["evidence_level"] == "REPRODUCED"

    model = b["model_identity"]
    assert model["logical_id"] == LOGICAL_ID
    assert model["revision"] == UPSTREAM_REVISION
    assert model["model_class"] == "speech-to-text-asr-encoder-decoder"

    ap = b["artifact_provenance"]
    assert ap["tracked"] is True
    assert ap["logical_artifact_id"] == LOGICAL_ID
    assert ap["upstream_revision"] == UPSTREAM_REVISION
    assert ap["identity_kind"] == "oci"
    assert ap["identity_digest"] == EXPECTED_DIGEST
    assert ap["verified"] is True

    obs = b["observations"]
    panel = obs["panel"]
    ds = panel["dataset"]
    assert ds["repository"] == DATASET_REPO
    assert ds["exact_revision"] == DATASET_REVISION
    assert ds["license"] == "CC-BY-4.0"
    assert ds["speaker_identity_available"] is False
    assert ds["speaker_claims_permitted"] is False

    source_files = panel["source_files"]
    assert len(source_files) == 3
    assert {x["config"] for x in source_files} == set(EXPECTED_CONFIGS)
    for src in source_files:
        assert src["sha256"].startswith("sha256:") and len(src["sha256"]) == 71
        assert int(src["size_bytes"]) > 1_000_000
        assert DATASET_REVISION in src["url"]

    samples = panel["samples"]
    assert len(samples) == 6
    assert len({x["sample_id"] for x in samples}) == 6
    for config, lang in EXPECTED_CONFIGS.items():
        group = [x for x in samples if x["config"] == config]
        assert len(group) == 2
        assert {int(x["intent_class"]) for x in group} == EXPECTED_INTENTS
        assert all(x["expected_language"] == lang for x in group)
        assert all(x["audio_sha256"].startswith("sha256:") and len(x["audio_sha256"]) == 71 for x in group)
        assert all(int(x["audio_size_bytes"]) > 0 for x in group)
        assert all(str(x["transcription"]).strip() for x in group)

    protocol = obs["protocol"]
    assert protocol["sample_rate"] == 16000
    assert protocol["snr_levels_db"] == [20.0, 10.0]
    assert protocol["language_mode"] == "automatic detection per condition"
    assert protocol["full_encoder_tensor_persisted"] is False
    assert protocol["speaker_identity_available"] is False

    results = obs["samples"]
    assert len(results) == 6
    for result in results:
        sample = result["sample"]
        assert sample["sample_id"] in {x["sample_id"] for x in samples}
        assert isinstance(result["noise_seed"], int) and result["noise_seed"] >= 0
        conditions = result["conditions"]
        assert len(conditions) == 3
        assert {c["id"] for c in conditions} == EXPECTED_CONDITIONS
        baseline = next(c for c in conditions if c["id"] == "baseline")
        assert baseline["snr_db"] is None
        assert abs(baseline["representation"]["feature_cosine_distance_from_baseline"]) <= 1e-6
        assert abs(baseline["representation"]["pooled_encoder_cosine_distance_from_baseline"]) <= 1e-6
        assert abs(baseline["representation"]["frame_geometry_from_baseline"]["mean_cosine_distance"]) <= 1e-6

        for c in conditions:
            audio = c["audio"]
            assert int(audio["samples"]) > 0
            assert finite(audio["duration_seconds"]) and audio["duration_seconds"] > 0
            assert finite(audio["rms"]) and audio["rms"] >= 0
            assert finite(audio["clipped_fraction"]) and 0 <= audio["clipped_fraction"] <= 1
            assert audio["sha256_float32le"].startswith("sha256:") and len(audio["sha256_float32le"]) == 71

            rep = c["representation"]
            assert rep["feature_shape_encoder_input"] == [80, 3000]
            assert rep["feature_sha256_float32"].startswith("sha256:") and len(rep["feature_sha256_float32"]) == 71
            assert len(rep["encoder_shape"]) == 3 and rep["encoder_shape"][0] == 1
            assert rep["encoder_sha256_float32"].startswith("sha256:") and len(rep["encoder_sha256_float32"]) == 71
            assert int(rep["active_encoder_frames_inferred"]) > 0
            for key in ("feature_cosine_distance_from_baseline", "feature_relative_frobenius_from_baseline", "pooled_encoder_cosine_distance_from_baseline"):
                assert finite(rep[key]) and rep[key] >= -1e-6
            fg = rep["frame_geometry_from_baseline"]
            assert int(fg["common_frames"]) > 0
            assert finite(fg["mean_cosine_distance"]) and fg["mean_cosine_distance"] >= -1e-6
            assert finite(fg["relative_frobenius_difference"]) and fg["relative_frobenius_difference"] >= -1e-6

            dec = c["decoder"]
            assert isinstance(dec["transcript"], str)
            assert isinstance(dec["detected_language"], str) and dec["detected_language"]
            assert finite(dec["language_probability"]) and 0 <= dec["language_probability"] <= 1
            assert isinstance(dec["language_matches_expected"], bool)
            for metrics_name in ("reference_text_metrics", "baseline_transcript_metrics"):
                tm = dec[metrics_name]
                assert int(tm["word_edit_distance"]) >= 0
                assert finite(tm["wer"]) and tm["wer"] >= 0
                assert isinstance(tm["exact_normalized_match"], bool)

    derived = b["derived_metrics"]
    counts = derived["panel_counts"]
    assert counts == {"samples": 6, "languages": 3, "conditions": 18}
    assert set(derived["per_language"]) == set(EXPECTED_CONFIGS)
    for config, lang in EXPECTED_CONFIGS.items():
        row = derived["per_language"][config]
        assert row["expected_language"] == lang
        for cid in EXPECTED_CONDITIONS:
            stats = row[cid]
            assert finite(stats["mean_reference_wer"]) and stats["mean_reference_wer"] >= 0
            assert 0 <= int(stats["detected_language_matches"]) <= 2
            assert finite(stats["mean_pooled_encoder_cosine_distance_from_baseline"])
            assert finite(stats["mean_frame_encoder_cosine_distance_from_baseline"])
    latent = derived["unchanged_transcript_with_moved_representation"]
    assert set(latent) == {"noise_20db", "noise_10db"}
    assert all(0 <= int(v) <= 6 for v in latent.values())
    checks = derived["portable_method_checks"]
    assert checks and all(v is True for v in checks.values())

    expected_hash = sha256_json({"observations": obs, "derived_metrics": derived})
    assert b["provenance"]["raw_output_hash"] == expected_hash

    print(json.dumps({
        "valid": True,
        "probe_id": b["probe_id"],
        "identity_digest": ap["identity_digest"],
        "dataset_revision": DATASET_REVISION,
        "samples": 6,
        "conditions": 18,
        "latent_before_output_counts": latent,
        "scientific_outcome_not_acceptance_gate": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
