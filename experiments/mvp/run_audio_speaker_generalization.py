#!/usr/bin/env python3
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
DATASET_REPO = "facebook/multilingual_librispeech"
DATASET_REVISION = "2e83e61823b4c47dcbcb1980bb88601274127609"
SAMPLE_RATE = 16000
ENCODER_INPUT_FRAMES = 3000
CONDITIONS = ("baseline", "gain_0.125", "snr_20db", "snr_10db", "silence_500ms")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def array_hash(x: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(x).tobytes(order="C"))


def rms(x: np.ndarray) -> float:
    a = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def normalize_chars(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text).casefold()
    return [c for c in t if not c.isspace() and (c.isalnum() or unicodedata.category(c).startswith("L"))]


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def char_distance(ref: str, cand: str) -> dict[str, Any]:
    a, b = normalize_chars(ref), normalize_chars(cand)
    e = edit_distance(a, b)
    return {
        "reference_chars": len(a),
        "candidate_chars": len(b),
        "char_edit_distance": e,
        "normalized_char_edit_distance": float(e / max(1, len(a))),
    }


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    x = np.asarray(a, dtype=np.float64).reshape(-1)
    y = np.asarray(b, dtype=np.float64).reshape(-1)
    den = float(np.linalg.norm(x) * np.linalg.norm(y))
    if den <= 1e-12:
        return 0.0 if np.allclose(x, y) else 1.0
    return float(1.0 - np.dot(x, y) / den)


def frame_compare(a: np.ndarray, b: np.ndarray, offset: int = 0) -> dict[str, Any]:
    if offset < 0 or offset >= b.shape[0]:
        raise RuntimeError(f"invalid frame offset {offset} for {b.shape}")
    n = min(a.shape[0], b.shape[0] - offset)
    aa = np.asarray(a[:n], dtype=np.float64)
    bb = np.asarray(b[offset:offset + n], dtype=np.float64)
    an = np.linalg.norm(aa, axis=-1)
    bn = np.linalg.norm(bb, axis=-1)
    den = an * bn
    dots = np.sum(aa * bb, axis=-1)
    cos = np.ones(n, dtype=np.float64)
    nz = den > 1e-12
    cos[nz] = dots[nz] / den[nz]
    cos[~nz] = np.where(np.linalg.norm(aa[~nz] - bb[~nz], axis=-1) <= 1e-12, 1.0, 0.0)
    return {
        "common_frames": int(n),
        "candidate_offset_frames": int(offset),
        "mean_cosine_distance": float(np.mean(1.0 - cos)),
        "relative_frobenius_difference": float(np.linalg.norm(aa - bb) / max(float(np.linalg.norm(aa)), 1e-12)),
    }


def encode(model: WhisperModel, audio: np.ndarray) -> dict[str, Any]:
    features = model.feature_extractor(audio)
    used = min(int(features.shape[-1]), int(model.feature_extractor.nb_max_frames))
    unpadded = np.asarray(features[:, :used], dtype=np.float32)
    padded = np.asarray(pad_or_trim(unpadded, length=ENCODER_INPUT_FRAMES), dtype=np.float32)
    enc = np.asarray(model.encode(padded))
    if enc.ndim == 2:
        enc = enc[np.newaxis, ...]
    enc = np.asarray(enc, dtype=np.float32)
    if enc.ndim != 3 or enc.shape[0] != 1 or not np.isfinite(enc).all():
        raise RuntimeError(f"invalid encoder output {enc.shape}")
    ratio = enc.shape[1] / float(ENCODER_INPUT_FRAMES)
    active_frames = max(1, min(enc.shape[1], int(math.ceil(used * ratio))))
    active = enc[0, :active_frames, :]
    return {
        "active": active,
        "pooled": active.mean(axis=0),
        "summary": {
            "feature_frames_used": used,
            "encoder_shape": list(enc.shape),
            "encoder_hash": array_hash(enc),
            "active_encoder_frames": active_frames,
            "temporal_ratio": float(ratio),
        },
    }


def transcribe(model: WhisperModel, audio: np.ndarray) -> dict[str, Any]:
    segs, info = model.transcribe(
        audio,
        language=None,
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=False,
        word_timestamps=False,
    )
    rows = []
    for s in segs:
        rows.append({
            "text": str(s.text),
            "avg_logprob": float(s.avg_logprob),
            "no_speech_prob": float(s.no_speech_prob),
        })
    text = "".join(r["text"] for r in rows).strip()
    return {
        "transcript": text,
        "detected_language": str(info.language),
        "language_probability": float(info.language_probability),
        "segment_count": len(rows),
        "mean_avg_logprob": float(np.mean([r["avg_logprob"] for r in rows])) if rows else None,
        "max_no_speech_prob": max([r["no_speech_prob"] for r in rows], default=None),
    }


def noise_seed(sample_id: str) -> int:
    return int(hashlib.sha256(sample_id.encode("utf-8")).hexdigest()[:8], 16)


def perturb(x: np.ndarray, condition: str, *, sample_id: str) -> np.ndarray:
    if condition == "baseline":
        return x.copy()
    if condition == "gain_0.125":
        return (x * 0.125).astype(np.float32)
    if condition.startswith("snr_"):
        db = float(condition.split("_")[1].replace("db", ""))
        rng = np.random.default_rng(noise_seed(sample_id))
        n = rng.standard_normal(x.shape, dtype=np.float32)
        n /= max(rms(n), 1e-8)
        target = max(rms(x), 1e-8) / (10.0 ** (db / 20.0))
        return np.clip(x + n * target, -1.0, 1.0).astype(np.float32)
    if condition == "silence_500ms":
        return np.concatenate([np.zeros(SAMPLE_RATE // 2, dtype=np.float32), x])
    raise KeyError(condition)


def mean_std(values: list[float]) -> dict[str, float]:
    a = np.asarray(values, dtype=np.float64)
    return {"mean": float(np.mean(a)), "std": float(np.std(a)), "min": float(np.min(a)), "max": float(np.max(a))}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--samples-dir", type=Path, required=True)
    p.add_argument("--panel", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started = time.perf_counter()
    panel = json.loads(args.panel.read_text(encoding="utf-8"))
    if panel["dataset_repository"] != DATASET_REPO or panel["dataset_revision"] != DATASET_REVISION:
        raise RuntimeError("dataset identity mismatch")

    t = time.perf_counter()
    model = WhisperModel(str(args.model_dir), device="cpu", compute_type="int8", local_files_only=True)
    model_load_seconds = time.perf_counter() - t

    t = time.perf_counter()
    language_rows = []
    for lang in panel["languages"]:
        speaker_rows = []
        for spec in lang["selected"]:
            path = args.samples_dir / spec["local_file"]
            raw = decode_audio(str(path), sampling_rate=SAMPLE_RATE).astype(np.float32)
            baseline_enc = encode(model, raw)
            baseline_asr = transcribe(model, raw)
            condition_rows = []
            for condition in CONDITIONS:
                audio = perturb(raw, condition, sample_id=spec["sample_id"])
                enc = baseline_enc if condition == "baseline" else encode(model, audio)
                asr = baseline_asr if condition == "baseline" else transcribe(model, audio)
                geometry = {
                    "pooled_cosine_distance": cosine_distance(baseline_enc["pooled"], enc["pooled"]),
                    "unaligned": frame_compare(baseline_enc["active"], enc["active"]),
                    "shift_aware": None,
                }
                if condition == "silence_500ms":
                    feature_offset = int(round(0.5 / model.feature_extractor.time_per_frame))
                    encoder_offset = int(round(feature_offset * enc["summary"]["temporal_ratio"]))
                    geometry["shift_aware"] = {
                        "feature_offset_frames": feature_offset,
                        "encoder_offset_frames": encoder_offset,
                        "encoder": frame_compare(baseline_enc["active"], enc["active"], encoder_offset),
                    }
                condition_rows.append({
                    "condition": condition,
                    "audio": {
                        "samples": int(audio.size),
                        "duration_seconds": float(audio.size / SAMPLE_RATE),
                        "rms": rms(audio),
                        "sha256_float32le": array_hash(np.asarray(audio, dtype="<f4")),
                    },
                    "representation": {
                        "encoder_shape": enc["summary"]["encoder_shape"],
                        "active_encoder_frames": enc["summary"]["active_encoder_frames"],
                        "encoder_hash": enc["summary"]["encoder_hash"],
                        "geometry_from_baseline": geometry,
                    },
                    "decoder": {
                        **asr,
                        "ground_truth_char_error": char_distance(spec["transcript"], asr["transcript"]),
                        "char_distance_from_baseline": char_distance(baseline_asr["transcript"], asr["transcript"]),
                        "language_matches_expected": asr["detected_language"] == lang["expected_language"],
                        "language_changed_from_baseline": asr["detected_language"] != baseline_asr["detected_language"],
                    },
                })
            repeat_enc = encode(model, raw)
            repeat_asr = transcribe(model, raw)
            speaker_rows.append({
                "panel_id": spec["panel_id"],
                "sample_id": spec["sample_id"],
                "speaker_id": spec["speaker_id"],
                "chapter_id": spec["chapter_id"],
                "source_row_index": spec["source_row_index"],
                "source_audio_sha256": spec["audio_sha256"],
                "ground_truth_transcript": spec["transcript"],
                "conditions": condition_rows,
                "baseline_repeat": {
                    "encoder_hash_equal": repeat_enc["summary"]["encoder_hash"] == baseline_enc["summary"]["encoder_hash"],
                    "transcript_equal": repeat_asr["transcript"] == baseline_asr["transcript"],
                    "detected_language_equal": repeat_asr["detected_language"] == baseline_asr["detected_language"],
                },
            })
        language_rows.append({
            "config": lang["config"],
            "expected_language": lang["expected_language"],
            "source_parquet_path": lang["source_parquet_path"],
            "source_parquet_sha256": lang["source_parquet_sha256"],
            "speakers": speaker_rows,
        })
    science_seconds = time.perf_counter() - t

    per_language = {}
    all_speakers = []
    for lang in language_rows:
        cond_summary = {}
        for condition in CONDITIONS:
            rows = [next(c for c in s["conditions"] if c["condition"] == condition) for s in lang["speakers"]]
            gt = [r["decoder"]["ground_truth_char_error"]["normalized_char_edit_distance"] for r in rows]
            rel = [r["decoder"]["char_distance_from_baseline"]["normalized_char_edit_distance"] for r in rows]
            frame = [r["representation"]["geometry_from_baseline"]["unaligned"]["mean_cosine_distance"] for r in rows]
            pooled = [r["representation"]["geometry_from_baseline"]["pooled_cosine_distance"] for r in rows]
            cond_summary[condition] = {
                "ground_truth_cer": mean_std(gt),
                "relative_to_baseline_cer": mean_std(rel),
                "frame_cosine_distance": mean_std(frame),
                "pooled_cosine_distance": mean_std(pooled),
                "expected_language_matches": sum(1 for r in rows if r["decoder"]["language_matches_expected"]),
                "exact_baseline_transcript_matches": sum(1 for r in rows if r["decoder"]["char_distance_from_baseline"]["char_edit_distance"] == 0),
            }
        baseline_cers = [next(c for c in s["conditions"] if c["condition"] == "baseline")["decoder"]["ground_truth_char_error"]["normalized_char_edit_distance"] for s in lang["speakers"]]
        per_language[lang["config"]] = {
            "speaker_ids": [s["speaker_id"] for s in lang["speakers"]],
            "baseline_speaker_cer_spread": mean_std(baseline_cers),
            "conditions": cond_summary,
        }
        all_speakers.extend(lang["speakers"])

    observations = {
        "dataset": {
            "repository": panel["dataset_repository"],
            "revision": panel["dataset_revision"],
            "license_spdx": panel["license_spdx"],
            "split": panel["split"],
            "selection_rule": panel["selection_rule"],
            "speakers_per_language": panel["speakers_per_language"],
        },
        "protocol": {
            "conditions": list(CONDITIONS),
            "sample_rate": SAMPLE_RATE,
            "language_mode": "auto-detect",
            "full_encoder_tensor_persisted": False,
            "noise_seed_rule": "sha256(sample_id) first 32 bits; same realization across SNR levels for each sample",
        },
        "languages": language_rows,
    }
    derived = {
        "language_count": len(language_rows),
        "speaker_count": len(all_speakers),
        "all_speaker_ids_distinct_within_language": all(len({s["speaker_id"] for s in lang["speakers"]}) == len(lang["speakers"]) for lang in language_rows),
        "all_baseline_encoder_repeats_exact": all(s["baseline_repeat"]["encoder_hash_equal"] for s in all_speakers),
        "all_baseline_transcript_repeats_exact": all(s["baseline_repeat"]["transcript_equal"] for s in all_speakers),
        "all_baseline_language_repeats_exact": all(s["baseline_repeat"]["detected_language_equal"] for s in all_speakers),
        "per_language": per_language,
    }
    raw_output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    git_sha = os.environ.get("GITHUB_SHA")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    bundle = {
        "probe_id": "audio-speaker-generalization-faster-whisper-tiny-v1",
        "instrument": "audio-speaker-aware-feature-encoder-decoder-generalization-suite",
        "instrument_version": "mvp-1",
        "model_identity": {
            "repository": UPSTREAM_REPO,
            "revision": UPSTREAM_REVISION,
            "logical_id": LOGICAL_ID,
            "model_class": "speech-to-text-asr-encoder-decoder",
        },
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
        "evidence_level": "REPRODUCED",
        "claim_tags": ["AUDIO", "MULTILINGUAL", "SPEAKER_VARIATION", "GROUND_TRUTH", "GENERALIZATION", "ENCODER_REPRESENTATION"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "population": "three deterministic MLS speakers from each of German, French, and Spanish 1-hour subsets; reconnaissance, not a population estimate",
            "selection": "first eligible distinct speakers in pinned parquet row order; no outcome-informed selection",
            "demographics": "speaker IDs establish distinct identities only; no demographic inference or ranking is made",
        },
        "known_assumptions": [
            "normalized Unicode character error is sufficient for a cross-language reconnaissance surface",
            "three speakers per language is enough to detect obvious within-language heterogeneity but not estimate its population distribution",
            "the pinned parquet bytes plus selected-row identities make the panel reproducible",
        ],
        "known_failure_modes": [
            "audiobook domain and read-speech style may not generalize to conversational speech",
            "speaker and chapter can be partially confounded",
            "Tiny Whisper model size can dominate some language-specific errors",
        ],
        "cost": {
            "model_load_seconds": model_load_seconds,
            "experiment_seconds": science_seconds,
            "total_script_seconds": time.perf_counter() - started,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        },
        "provenance": {
            "run_id": str(run_id),
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
            "randomness": {"noise_seed_rule": "sha256(sample_id)[0:8]", "beam_size": 1, "temperature": 0.0},
            "raw_input_hash": sha256_json(panel),
            "raw_output_hash": raw_output_hash,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "languages": derived["language_count"],
        "speakers": derived["speaker_count"],
        "all_repeats_exact": derived["all_baseline_encoder_repeats_exact"] and derived["all_baseline_transcript_repeats_exact"],
        "science_seconds": science_seconds,
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
