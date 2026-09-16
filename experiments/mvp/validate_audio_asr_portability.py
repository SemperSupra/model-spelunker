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
FIXTURE_COMMIT = "6e3be77e1a105e59086e3e21ff5f609fd6fa89a5"
VARIANT_IDS = {"baseline", "quiet_x0_25", "prepend_silence_500ms", "noise_20db", "silence_control", "tone_440hz_control"}


def sha256_json(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def finite_or_none(v) -> bool:
    return v is None or (isinstance(v, (int, float)) and math.isfinite(float(v)))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    args = p.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    jsonschema.validate(bundle, json.loads(SCHEMA.read_text(encoding="utf-8")))

    assert bundle["probe_id"] == "audio-asr-portability-faster-whisper-tiny-v1"
    assert bundle["instrument"] == "audio-transcript-confidence-and-perturbation-suite"
    assert bundle["access_tier"] == "A1"
    assert bundle["evidence_level"] == "REPRODUCED"

    model = bundle["model_identity"]
    assert model["logical_id"] == LOGICAL_ID
    assert model["revision"] == UPSTREAM_REVISION
    assert model["model_class"] == "speech-to-text-asr-encoder-decoder"

    ap = bundle["artifact_provenance"]
    assert ap["tracked"] is True
    assert ap["logical_artifact_id"] == LOGICAL_ID
    assert ap["identity_kind"] == "oci"
    assert ap["identity_digest"] == EXPECTED_DIGEST
    assert ap["verified"] is True

    obs = bundle["observations"]
    fixture = obs["fixture"]
    assert fixture["repository"] == "openai/whisper"
    assert fixture["commit_sha"] == FIXTURE_COMMIT
    assert fixture["path"] == "tests/jfk.flac"
    assert fixture["sha256"].startswith("sha256:") and len(fixture["sha256"]) == 71
    assert int(fixture["size_bytes"]) > 0
    assert obs["sample_rate"] == 16000

    rows = obs["variants"]
    assert len(rows) == 6
    assert {row["id"] for row in rows} == VARIANT_IDS
    for row in rows:
        audio = row["audio"]
        assert audio["sample_rate"] == 16000
        assert int(audio["samples"]) > 0
        assert isinstance(audio["duration_seconds"], (int, float)) and audio["duration_seconds"] > 0
        assert isinstance(audio["rms"], (int, float)) and math.isfinite(float(audio["rms"])) and audio["rms"] >= 0
        assert isinstance(audio["peak_abs"], (int, float)) and math.isfinite(float(audio["peak_abs"])) and audio["peak_abs"] >= 0
        assert audio["sha256_float32le"].startswith("sha256:") and len(audio["sha256_float32le"]) == 71
        result = row["result"]
        assert isinstance(result["transcript"], str)
        assert isinstance(result["segments"], list)
        assert result["segment_count"] == len(result["segments"])
        assert result["language"] == "en"
        for key in ("language_probability", "duration", "duration_after_vad", "mean_segment_avg_logprob", "mean_no_speech_prob", "max_no_speech_prob", "mean_compression_ratio"):
            assert finite_or_none(result[key])
        for seg in result["segments"]:
            assert isinstance(seg["text"], str)
            for key in ("start", "end", "avg_logprob", "compression_ratio", "no_speech_prob", "temperature"):
                assert finite_or_none(seg[key])
        td = row["transcript_distance_from_baseline"]
        assert isinstance(td["reference_words"], int) and td["reference_words"] >= 0
        assert isinstance(td["candidate_words"], int) and td["candidate_words"] >= 0
        assert isinstance(td["word_edit_distance"], int) and td["word_edit_distance"] >= 0
        assert isinstance(td["normalized_word_edit_distance"], (int, float)) and math.isfinite(float(td["normalized_word_edit_distance"]))
        assert set(row["expected_phrase_presence"]) == {"my fellow americans", "your country", "do for you"}

    baseline = next(row for row in rows if row["id"] == "baseline")
    assert baseline["transcript_distance_from_baseline"]["word_edit_distance"] == 0

    repeat = obs["baseline_repeat"]
    assert isinstance(repeat["transcript"], str)
    derived = bundle["derived_metrics"]
    assert isinstance(derived["baseline_repeat_exact_transcript"], bool)
    assert derived["baseline_repeat_exact_transcript"] is True
    assert finite_or_none(derived["baseline_repeat_mean_logprob_abs_delta"])
    if derived["baseline_repeat_mean_logprob_abs_delta"] is not None:
        assert derived["baseline_repeat_mean_logprob_abs_delta"] <= 1e-6
    assert set(derived["speech_variant_normalized_word_edit_distances"]) == {"baseline", "quiet_x0_25", "prepend_silence_500ms", "noise_20db"}
    assert set(derived["no_speech_control_transcript_word_counts"]) == {"silence_control", "tone_440hz_control"}
    checks = derived["portable_instrument_checks"]
    assert checks and all(v is True for v in checks.values())

    expected_hash = sha256_json({"observations": obs, "derived_metrics": derived})
    assert bundle["provenance"]["raw_output_hash"] == expected_hash

    print(json.dumps({
        "valid": True,
        "probe_id": bundle["probe_id"],
        "identity_digest": ap["identity_digest"],
        "baseline_transcript": baseline["result"]["transcript"],
        "speech_edit_distances": derived["speech_variant_normalized_word_edit_distances"],
        "control_word_counts": derived["no_speech_control_transcript_word_counts"],
        "quality_outcome_not_acceptance_gate": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
