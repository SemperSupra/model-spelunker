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
EXPECTED_CONFIGS = {"en_us", "ru_ru", "ar_eg", "sw_ke", "hi_in", "th_th", "ja_jp"}
EXPECTED_CONDITIONS = {"baseline", "snr_20db", "snr_10db"}


def finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def sha256_json(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    args = p.parse_args()
    b = json.loads(args.bundle.read_text(encoding="utf-8"))
    jsonschema.validate(b, json.loads(SCHEMA.read_text(encoding="utf-8")))

    assert b["probe_id"] == "audio-fleurs-seven-geogroup-generalization-v1"
    assert b["instrument"] == "audio-fleurs-feature-encoder-decoder-generalization-suite"
    assert b["access_tier"] == "A2"
    assert b["evidence_level"] == "OBSERVED"
    assert b["artifact_provenance"]["identity_digest"] == EXPECTED_DIGEST
    assert b["artifact_provenance"]["verified"] is True

    obs = b["observations"]
    corpus = obs["corpus_manifest"]
    assert corpus["dataset"]["id"] == "google/fleurs"
    assert corpus["dataset"]["license"] == "cc-by-4.0"
    revision = corpus["dataset"]["revision"]
    assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision.lower())
    assert corpus["acquisition"]["revision_stable_during_acquisition"] is True
    assert len(corpus["samples"]) == 7
    assert {x["config"] for x in corpus["samples"]} == EXPECTED_CONFIGS
    assert len({x["group"] for x in corpus["samples"]}) == 7
    for x in corpus["samples"]:
        assert x["audio_sha256"].startswith("sha256:") and len(x["audio_sha256"]) == 71
        assert x["reference_sha256_utf8"].startswith("sha256:") and len(x["reference_sha256_utf8"]) == 71
        assert int(x["audio_size_bytes"]) > 1000
        assert isinstance(x["reference"], str) and x["reference"].strip()

    langs = obs["languages"]
    assert len(langs) == 7
    assert {x["config"] for x in langs} == EXPECTED_CONFIGS
    assert len({x["group"] for x in langs}) == 7
    for lang in langs:
        assert lang["audio_sha256"].startswith("sha256:")
        rows = lang["conditions"]
        assert {x["id"] for x in rows} == EXPECTED_CONDITIONS
        for row in rows:
            enc = row["encoder"]
            assert len(enc["encoder_shape"]) == 3 and enc["encoder_shape"][0] == 1
            assert enc["encoder_sha256_float32"].startswith("sha256:") and len(enc["encoder_sha256_float32"]) == 71
            geom = enc["geometry_from_baseline"]
            for key in ("pooled_cosine_distance", "mean_frame_cosine_distance", "relative_frobenius_difference"):
                assert finite(geom[key]) and geom[key] >= -1e-6
            forced = row["forced_decoder"]
            assert isinstance(forced["transcript"], str)
            ref = forced["reference_cer"]
            assert finite(ref["normalized_char_error_rate"]) and ref["normalized_char_error_rate"] >= 0
            if row["id"] == "baseline":
                auto = row["auto_decoder"]
                assert isinstance(auto["detected_language"], str)
                assert isinstance(auto["language_matches_expected"], bool)
                assert finite(auto["reference_cer"]["normalized_char_error_rate"])
            else:
                assert isinstance(forced["changed_from_baseline"], bool)

    d = b["derived_metrics"]
    assert d["language_count"] == 7
    assert d["geographic_group_count"] == 7
    assert 0 <= d["baseline_auto_language_id_correct"] <= 7
    for v in d["mean_normalized_character_error_rate"].values():
        assert finite(v) and v >= 0
    for v in d["mean_encoder_frame_cosine_distance_from_baseline"].values():
        assert finite(v) and v >= -1e-6
    assert set(d["per_language"]) == EXPECTED_CONFIGS
    assert d["baseline_repeat"]["encoder_hash_equal"] is True
    assert d["baseline_repeat"]["forced_transcript_equal"] is True
    assert all(v is True for v in d["portable_method_checks"].values())

    expected = sha256_json({"observations": obs, "derived_metrics": d})
    assert b["provenance"]["raw_output_hash"] == expected

    print(json.dumps({
        "valid": True,
        "dataset_revision": revision,
        "languages": sorted(EXPECTED_CONFIGS),
        "langid_correct": d["baseline_auto_language_id_correct"],
        "mean_cer": d["mean_normalized_character_error_rate"],
        "scientific_outcome_not_acceptance_gate": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
