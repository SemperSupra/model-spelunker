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
EXPECTED_DIGEST = "sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
MODEL_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
DATASET_REPO = "facebook/multilingual_librispeech"
DATASET_REVISION = "2e83e61823b4c47dcbcb1980bb88601274127609"
CONFIGS = {"german": "de", "french": "fr", "spanish": "es"}
CONDITIONS = {"baseline", "gain_0.125", "snr_20db", "snr_10db", "silence_500ms"}


def finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def sha256_json(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def validate_stats(stats: dict) -> None:
    assert set(stats) == {"mean", "std", "min", "max"}
    assert all(finite(v) and float(v) >= -1e-9 for v in stats.values())
    assert stats["min"] <= stats["mean"] <= stats["max"]
    assert stats["std"] >= 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    args = p.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    jsonschema.validate(bundle, json.loads(SCHEMA.read_text(encoding="utf-8")))

    assert bundle["probe_id"] == "audio-speaker-generalization-faster-whisper-tiny-v1"
    assert bundle["instrument"] == "audio-speaker-aware-feature-encoder-decoder-generalization-suite"
    assert bundle["access_tier"] == "A2"
    assert bundle["evidence_level"] == "REPRODUCED"
    assert bundle["model_identity"]["revision"] == MODEL_REVISION
    ap = bundle["artifact_provenance"]
    assert ap["tracked"] is True and ap["verified"] is True
    assert ap["identity_digest"] == EXPECTED_DIGEST
    assert ap["upstream_revision"] == MODEL_REVISION

    obs = bundle["observations"]
    ds = obs["dataset"]
    assert ds["repository"] == DATASET_REPO
    assert ds["revision"] == DATASET_REVISION
    assert ds["license_spdx"] == "CC-BY-4.0"
    assert ds["split"] == "1_hours"
    assert ds["speakers_per_language"] == 3
    assert set(obs["protocol"]["conditions"]) == CONDITIONS
    assert obs["protocol"]["full_encoder_tensor_persisted"] is False

    languages = obs["languages"]
    assert len(languages) == 3
    assert {x["config"] for x in languages} == set(CONFIGS)
    all_speakers = []
    for lang in languages:
        config = lang["config"]
        assert lang["expected_language"] == CONFIGS[config]
        assert lang["source_parquet_path"].endswith("1_hours-00000-of-00001.parquet")
        assert lang["source_parquet_sha256"].startswith("sha256:") and len(lang["source_parquet_sha256"]) == 71
        speakers = lang["speakers"]
        assert len(speakers) == 3
        ids = [s["speaker_id"] for s in speakers]
        assert len(set(ids)) == 3
        for speaker in speakers:
            all_speakers.append(speaker)
            assert speaker["sample_id"] and speaker["speaker_id"]
            assert speaker["source_audio_sha256"].startswith("sha256:") and len(speaker["source_audio_sha256"]) == 71
            assert speaker["ground_truth_transcript"]
            rows = speaker["conditions"]
            assert len(rows) == 5 and {r["condition"] for r in rows} == CONDITIONS
            shapes = set()
            for row in rows:
                audio = row["audio"]
                assert int(audio["samples"]) > 0
                assert finite(audio["duration_seconds"]) and audio["duration_seconds"] > 0
                assert finite(audio["rms"]) and audio["rms"] >= 0
                assert audio["sha256_float32le"].startswith("sha256:")
                rep = row["representation"]
                shape = tuple(rep["encoder_shape"])
                assert len(shape) == 3 and shape[0] == 1 and shape[1] > 0 and shape[2] > 0
                shapes.add(shape)
                assert rep["encoder_hash"].startswith("sha256:")
                assert 1 <= rep["active_encoder_frames"] <= shape[1]
                geom = rep["geometry_from_baseline"]
                assert finite(geom["pooled_cosine_distance"]) and geom["pooled_cosine_distance"] >= -1e-6
                g = geom["unaligned"]
                assert int(g["common_frames"]) > 0
                assert finite(g["mean_cosine_distance"]) and g["mean_cosine_distance"] >= -1e-6
                assert finite(g["relative_frobenius_difference"]) and g["relative_frobenius_difference"] >= -1e-6
                if row["condition"] == "silence_500ms":
                    assert geom["shift_aware"] is not None
                    assert geom["shift_aware"]["feature_offset_frames"] == 50
                    assert geom["shift_aware"]["encoder_offset_frames"] == 25
                else:
                    assert geom["shift_aware"] is None
                dec = row["decoder"]
                assert isinstance(dec["transcript"], str)
                assert isinstance(dec["detected_language"], str) and dec["detected_language"]
                assert finite(dec["language_probability"])
                for field in ("ground_truth_char_error", "char_distance_from_baseline"):
                    metric = dec[field]
                    assert int(metric["reference_chars"]) > 0
                    assert int(metric["char_edit_distance"]) >= 0
                    assert finite(metric["normalized_char_edit_distance"]) and metric["normalized_char_edit_distance"] >= 0
                assert isinstance(dec["language_matches_expected"], bool)
                assert isinstance(dec["language_changed_from_baseline"], bool)
            assert len(shapes) == 1
            baseline = next(r for r in rows if r["condition"] == "baseline")
            assert baseline["decoder"]["char_distance_from_baseline"]["char_edit_distance"] == 0
            assert abs(baseline["representation"]["geometry_from_baseline"]["pooled_cosine_distance"]) <= 1e-6
            assert abs(baseline["representation"]["geometry_from_baseline"]["unaligned"]["mean_cosine_distance"]) <= 1e-6
            repeat = speaker["baseline_repeat"]
            assert repeat["encoder_hash_equal"] is True
            assert repeat["transcript_equal"] is True
            assert repeat["detected_language_equal"] is True

    derived = bundle["derived_metrics"]
    assert derived["language_count"] == 3
    assert derived["speaker_count"] == 9
    assert derived["all_speaker_ids_distinct_within_language"] is True
    assert derived["all_baseline_encoder_repeats_exact"] is True
    assert derived["all_baseline_transcript_repeats_exact"] is True
    assert derived["all_baseline_language_repeats_exact"] is True
    assert set(derived["per_language"]) == set(CONFIGS)
    for config, summary in derived["per_language"].items():
        assert len(summary["speaker_ids"]) == 3 and len(set(summary["speaker_ids"])) == 3
        validate_stats(summary["baseline_speaker_cer_spread"])
        assert set(summary["conditions"]) == CONDITIONS
        for condition, stats in summary["conditions"].items():
            for key in ("ground_truth_cer", "relative_to_baseline_cer", "frame_cosine_distance", "pooled_cosine_distance"):
                validate_stats(stats[key])
            assert 0 <= stats["expected_language_matches"] <= 3
            assert 0 <= stats["exact_baseline_transcript_matches"] <= 3

    expected_hash = sha256_json({"observations": obs, "derived_metrics": derived})
    assert bundle["provenance"]["raw_output_hash"] == expected_hash
    assert finite(bundle["cost"]["model_load_seconds"])
    assert finite(bundle["cost"]["experiment_seconds"])
    assert finite(bundle["cost"]["peak_rss_mib"])

    print(json.dumps({
        "valid": True,
        "probe_id": bundle["probe_id"],
        "languages": derived["language_count"],
        "speakers": derived["speaker_count"],
        "speaker_ids": {k: v["speaker_ids"] for k, v in derived["per_language"].items()},
        "scientific_outcome_not_acceptance_gate": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
