#!/usr/bin/env python3
"""Rep 33: FLEURS seven-geogroup multilingual audio falsifier."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import resource
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio, pad_or_trim

LOGICAL_ID = "asr/faster-whisper/tiny"
UPSTREAM_REPO = "Systran/faster-whisper-tiny"
UPSTREAM_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
FOUNDRY_DIGEST = "sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
FOUNDRY_CATALOG_REF = "SemperSupra/model-artifact-foundry@6622753fd5914be87fb1b6d987ceb7cae46c7ff5:catalog/approved.json"
SAMPLE_RATE = 16000
ENCODER_INPUT_FRAMES = 3000
SNR_LEVELS = (20.0, 10.0)
EXPECTED_CONFIGS = {"en_us", "ru_ru", "ar_eg", "sw_ke", "hi_in", "th_th", "ja_jp"}


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def array_hash(x: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(x).tobytes(order="C"))


def rms(x: np.ndarray) -> float:
    y = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(y * y))) if y.size else 0.0


def normalize_chars(text: str) -> list[str]:
    s = unicodedata.normalize("NFKC", text).casefold()
    return [ch for ch in s if unicodedata.category(ch)[:1] in {"L", "N", "M"}]


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def cer(reference: str, candidate: str) -> dict[str, Any]:
    a, b = normalize_chars(reference), normalize_chars(candidate)
    edits = edit_distance(a, b)
    return {
        "reference_chars": len(a),
        "candidate_chars": len(b),
        "char_edit_distance": edits,
        "normalized_char_error_rate": float(edits / max(1, len(a))),
        "exact_normalized_match": a == b,
    }


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    x = np.asarray(a, dtype=np.float64).reshape(-1)
    y = np.asarray(b, dtype=np.float64).reshape(-1)
    den = float(np.linalg.norm(x) * np.linalg.norm(y))
    if den <= 1e-12:
        return 0.0 if np.allclose(x, y) else 1.0
    return float(1.0 - np.dot(x, y) / den)


def encode(model: WhisperModel, audio: np.ndarray) -> dict[str, Any]:
    features = model.feature_extractor(audio)
    used = min(int(features.shape[-1]), int(model.feature_extractor.nb_max_frames))
    unpadded = np.asarray(features[:, :used], dtype=np.float32)
    padded = np.asarray(pad_or_trim(unpadded, length=ENCODER_INPUT_FRAMES), dtype=np.float32)
    encoded = np.asarray(model.encode(padded))
    if encoded.ndim == 2:
        encoded = encoded[np.newaxis, ...]
    encoded = np.asarray(encoded, dtype=np.float32)
    if encoded.ndim != 3 or encoded.shape[0] != 1 or not np.isfinite(encoded).all():
        raise RuntimeError(f"invalid encoder output: {encoded.shape}")
    ratio = encoded.shape[1] / float(ENCODER_INPUT_FRAMES)
    active_frames = max(1, min(encoded.shape[1], int(math.ceil(used * ratio))))
    active = encoded[0, :active_frames]
    return {
        "active": active,
        "pooled": active.mean(axis=0),
        "summary": {
            "feature_frames_used": used,
            "encoder_shape": list(encoded.shape),
            "encoder_sha256_float32": array_hash(encoded),
            "active_encoder_frames": active_frames,
        },
    }


def geometry(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    a = np.asarray(reference["active"], dtype=np.float64)
    b = np.asarray(candidate["active"], dtype=np.float64)
    n = min(a.shape[0], b.shape[0])
    a, b = a[:n], b[:n]
    den = np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1)
    dots = np.sum(a * b, axis=-1)
    cos = np.ones(n, dtype=np.float64)
    nz = den > 1e-12
    cos[nz] = dots[nz] / den[nz]
    cos[~nz] = np.where(np.linalg.norm(a[~nz] - b[~nz], axis=-1) <= 1e-12, 1.0, 0.0)
    return {
        "common_active_frames": int(n),
        "pooled_cosine_distance": cosine_distance(reference["pooled"], candidate["pooled"]),
        "mean_frame_cosine_distance": float(np.mean(1.0 - cos)),
        "relative_frobenius_difference": float(np.linalg.norm(a - b) / max(float(np.linalg.norm(a)), 1e-12)),
    }


def transcribe(model: WhisperModel, audio: np.ndarray, language: str | None) -> dict[str, Any]:
    segments, info = model.transcribe(
        audio,
        language=language,
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=False,
        word_timestamps=False,
    )
    rows = []
    for seg in segments:
        rows.append({
            "text": str(seg.text),
            "avg_logprob": float(seg.avg_logprob),
            "no_speech_prob": float(seg.no_speech_prob),
        })
    transcript = "".join(x["text"] for x in rows).strip()
    return {
        "transcript": transcript,
        "segment_count": len(rows),
        "detected_language": str(info.language),
        "language_probability": float(info.language_probability),
        "mean_avg_logprob": float(np.mean([x["avg_logprob"] for x in rows])) if rows else None,
        "max_no_speech_prob": max([x["no_speech_prob"] for x in rows], default=None),
    }


def noisy(audio: np.ndarray, snr_db: float, seed: int) -> tuple[np.ndarray, dict[str, Any]]:
    x = np.asarray(audio, dtype=np.float32)
    rng = np.random.default_rng(seed)
    n = rng.standard_normal(x.shape, dtype=np.float32)
    n /= max(rms(n), 1e-8)
    target = max(rms(x), 1e-8) / (10.0 ** (snr_db / 20.0))
    raw = x + n * target
    clipped = np.clip(raw, -1.0, 1.0).astype(np.float32)
    return clipped, {
        "type": "additive_white_noise",
        "snr_db": snr_db,
        "rng_seed": seed,
        "clipped_fraction": float(np.mean(np.abs(raw) > 1.0)),
    }


def avg(values: list[float]) -> float:
    return float(sum(values) / len(values))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--corpus-manifest", type=Path, required=True)
    p.add_argument("--audio-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started = time.perf_counter()
    corpus = json.loads(args.corpus_manifest.read_text(encoding="utf-8"))
    samples = corpus["samples"]
    if len(samples) != 7 or {s["config"] for s in samples} != EXPECTED_CONFIGS:
        raise RuntimeError("unexpected FLEURS panel")

    for s in samples:
        if sha256_bytes((args.audio_dir / s["audio_file"]).read_bytes()) != s["audio_sha256"]:
            raise RuntimeError(f"audio identity mismatch: {s['config']}")

    t = time.perf_counter()
    model = WhisperModel(str(args.model_dir), device="cpu", compute_type="int8", local_files_only=True)
    model_load_seconds = time.perf_counter() - t

    t = time.perf_counter()
    languages = []
    for s in samples:
        audio = decode_audio(str(args.audio_dir / s["audio_file"]), sampling_rate=SAMPLE_RATE).astype(np.float32)
        reference = s["reference"]
        expected = s["whisper_code"]
        base_enc = encode(model, audio)
        forced = transcribe(model, audio, expected)
        auto = transcribe(model, audio, None)
        conditions = [{
            "id": "baseline",
            "transform": {"type": "identity"},
            "encoder": {**base_enc["summary"], "geometry_from_baseline": {
                "common_active_frames": base_enc["active"].shape[0],
                "pooled_cosine_distance": 0.0,
                "mean_frame_cosine_distance": 0.0,
                "relative_frobenius_difference": 0.0,
            }},
            "forced_decoder": {**forced, "reference_cer": cer(reference, forced["transcript"])},
            "auto_decoder": {
                **auto,
                "reference_cer": cer(reference, auto["transcript"]),
                "language_matches_expected": auto["detected_language"] == expected,
            },
        }]
        seed = int.from_bytes(hashlib.sha256(s["config"].encode("utf-8")).digest()[:4], "big")
        for snr in SNR_LEVELS:
            perturbed, transform = noisy(audio, snr, seed)
            enc = encode(model, perturbed)
            dec = transcribe(model, perturbed, expected)
            conditions.append({
                "id": f"snr_{int(snr)}db",
                "transform": transform,
                "encoder": {**enc["summary"], "geometry_from_baseline": geometry(base_enc, enc)},
                "forced_decoder": {
                    **dec,
                    "reference_cer": cer(reference, dec["transcript"]),
                    "changed_from_baseline": normalize_chars(dec["transcript"]) != normalize_chars(forced["transcript"]),
                },
            })
        languages.append({
            "config": s["config"],
            "whisper_code": expected,
            "group": s["group"],
            "row_idx": s["row_idx"],
            "dataset_row_id": s.get("dataset_row_id"),
            "reference": reference,
            "reference_sha256_utf8": s["reference_sha256_utf8"],
            "audio_sha256": s["audio_sha256"],
            "conditions": conditions,
        })

    en = next(x for x in languages if x["config"] == "en_us")
    en_sample = next(x for x in samples if x["config"] == "en_us")
    repeat_audio = decode_audio(str(args.audio_dir / en_sample["audio_file"]), sampling_rate=SAMPLE_RATE).astype(np.float32)
    repeat_enc = encode(model, repeat_audio)
    repeat_dec = transcribe(model, repeat_audio, "en")
    en_base = next(x for x in en["conditions"] if x["id"] == "baseline")
    repeat = {
        "encoder_hash_equal": repeat_enc["summary"]["encoder_sha256_float32"] == en_base["encoder"]["encoder_sha256_float32"],
        "forced_transcript_equal": normalize_chars(repeat_dec["transcript"]) == normalize_chars(en_base["forced_decoder"]["transcript"]),
    }

    baseline_cer, auto_cer, c20, c10, e20, e10 = [], [], [], [], [], []
    langid = 0
    changed20 = changed10 = 0
    per_language = {}
    for lang in languages:
        by = {x["id"]: x for x in lang["conditions"]}
        b, n20, n10 = by["baseline"], by["snr_20db"], by["snr_10db"]
        vals = {
            "baseline_forced_cer": float(b["forced_decoder"]["reference_cer"]["normalized_char_error_rate"]),
            "baseline_auto_cer": float(b["auto_decoder"]["reference_cer"]["normalized_char_error_rate"]),
            "snr_20db_forced_cer": float(n20["forced_decoder"]["reference_cer"]["normalized_char_error_rate"]),
            "snr_10db_forced_cer": float(n10["forced_decoder"]["reference_cer"]["normalized_char_error_rate"]),
            "snr_20db_encoder_frame_distance": float(n20["encoder"]["geometry_from_baseline"]["mean_frame_cosine_distance"]),
            "snr_10db_encoder_frame_distance": float(n10["encoder"]["geometry_from_baseline"]["mean_frame_cosine_distance"]),
            "auto_language_matches_expected": bool(b["auto_decoder"]["language_matches_expected"]),
        }
        per_language[lang["config"]] = vals
        baseline_cer.append(vals["baseline_forced_cer"]); auto_cer.append(vals["baseline_auto_cer"])
        c20.append(vals["snr_20db_forced_cer"]); c10.append(vals["snr_10db_forced_cer"])
        e20.append(vals["snr_20db_encoder_frame_distance"]); e10.append(vals["snr_10db_encoder_frame_distance"])
        langid += int(vals["auto_language_matches_expected"])
        changed20 += int(bool(n20["forced_decoder"]["changed_from_baseline"]))
        changed10 += int(bool(n10["forced_decoder"]["changed_from_baseline"]))

    derived = {
        "language_count": len(languages),
        "geographic_group_count": len({x["group"] for x in languages}),
        "baseline_auto_language_id_correct": langid,
        "mean_normalized_character_error_rate": {
            "baseline_forced": avg(baseline_cer),
            "baseline_auto": avg(auto_cer),
            "snr_20db_forced": avg(c20),
            "snr_10db_forced": avg(c10),
        },
        "transcript_changed_from_forced_baseline": {"snr_20db": changed20, "snr_10db": changed10},
        "mean_encoder_frame_cosine_distance_from_baseline": {"snr_20db": avg(e20), "snr_10db": avg(e10)},
        "per_language": per_language,
        "baseline_repeat": repeat,
        "portable_method_checks": {
            "seven_geographic_groups_observed": len({x["group"] for x in languages}) == 7,
            "benchmark_references_observed": True,
            "auto_language_detection_observed": True,
            "forced_language_asr_observed": True,
            "encoder_geometry_observed": True,
            "baseline_repeat_exact": bool(repeat["encoder_hash_equal"] and repeat["forced_transcript_equal"]),
        },
    }
    observations = {
        "corpus_manifest": corpus,
        "protocol": {
            "sample_rate": SAMPLE_RATE,
            "snr_db_levels": list(SNR_LEVELS),
            "baseline_auto_language_detection": True,
            "noisy_conditions_force_expected_language": True,
            "unicode_normalization": "NFKC casefold; retain Unicode letters/numbers/marks; ignore whitespace/punctuation",
            "full_encoder_tensor_persisted": False,
        },
        "languages": languages,
    }
    output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    science_seconds = time.perf_counter() - t
    git_sha = os.environ.get("GITHUB_SHA")
    bundle = {
        "probe_id": "audio-fleurs-seven-geogroup-generalization-v1",
        "instrument": "audio-fleurs-feature-encoder-decoder-generalization-suite",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": UPSTREAM_REPO, "revision": UPSTREAM_REVISION, "logical_id": LOGICAL_ID, "model_class": "speech-to-text-asr-encoder-decoder"},
        "artifact_provenance": {
            "tracked": True,
            "foundry_repository": "SemperSupra/model-artifact-foundry",
            "logical_artifact_id": LOGICAL_ID,
            "upstream_provider": "huggingface",
            "upstream_repository": UPSTREAM_REPO,
            "upstream_revision": UPSTREAM_REVISION,
            "identity_kind": "oci",
            "identity_digest": FOUNDRY_DIGEST,
            "foundry_record_ref": FOUNDRY_CATALOG_REF,
            "consumer_selection_ref": f"model-spelunker@{git_sha}" if git_sha else None,
            "verified": True,
            "verification_ref": "digest-pinned approved Foundry hydration with offline local reuse",
            "tokenizer_artifact": None,
        },
        "access_tier": "A2",
        "evidence_level": "OBSERVED",
        "claim_tags": ["AUDIO", "MULTILINGUAL", "FLEURS", "GENERALIZATION", "LANGUAGE_ID", "ENCODER_REPRESENTATION"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "population": "one FLEURS test row per geographic group; reconnaissance, not language- or population-level performance",
            "acquisition": "Hub repository revision is checked before/after acquisition and consumed bytes are hashed; Dataset Viewer cached assets are not promoted as an immutable corpus artifact",
            "noise": "one deterministic white-noise realization per language at each SNR",
        },
        "known_assumptions": [
            "forced-language decoding separates ASR from baseline LangID errors",
            "Unicode character error is preferable to whitespace WER for this mixed-script reconnaissance panel",
            "20 dB and 10 dB are inherited falsifier levels, not claimed universal thresholds",
        ],
        "known_failure_modes": [
            "one row per language cannot estimate within-language speaker or utterance variance",
            "Dataset Viewer may lag the Hub repository even when the repository SHA is stable; exact consumed bytes are therefore retained by hash",
            "normalization choices affect cross-script error rates",
        ],
        "cost": {
            "model_load_seconds": model_load_seconds,
            "experiment_seconds": science_seconds,
            "total_script_seconds": time.perf_counter() - started,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        },
        "provenance": {
            "run_id": str(os.environ.get("GITHUB_RUN_ID", "local")),
            "code_revision": git_sha,
            "model_revision": UPSTREAM_REVISION,
            "tokenizer_revision": UPSTREAM_REVISION,
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "numpy": np.__version__,
                "faster_whisper": importlib.metadata.version("faster-whisper"),
                "ctranslate2": importlib.metadata.version("ctranslate2"),
            },
            "randomness": {"noise_seed": "first 32 bits sha256(config)", "beam_size": 1, "temperature": 0.0},
            "raw_input_hash": sha256_json(corpus),
            "raw_output_hash": output_hash,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset_revision": corpus["dataset"]["revision"],
        "language_count": len(languages),
        "langid_correct": f"{langid}/7",
        "mean_cer": derived["mean_normalized_character_error_rate"],
        "transcript_changes": derived["transcript_changed_from_forced_baseline"],
        "encoder_distance": derived["mean_encoder_frame_cosine_distance_from_baseline"],
        "science_seconds": science_seconds,
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
