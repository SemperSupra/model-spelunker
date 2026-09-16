#!/usr/bin/env python3
"""Rep 28: audio dose-response across feature, encoder, and ASR output surfaces.

One approved Faster-Whisper Tiny load is reused across gain, deterministic SNR,
and known leading-silence sweeps on the pinned JFK fixture. Leading-silence cases
also receive shift-aware feature/encoder comparisons using the known injected offset.
"""
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
FIXTURE_SHA256 = "sha256:63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715"
SAMPLE_RATE = 16000
ENCODER_INPUT_FRAMES = 3000
GAIN_FACTORS = [0.5, 0.25, 0.125, 0.0625, 0.03125]
SNR_DB_VALUES = [40.0, 30.0, 20.0, 10.0, 5.0, 0.0]
SILENCE_SECONDS = [0.25, 0.5, 1.0, 2.0]


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def array_hash(x: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(x).tobytes(order="C"))


def rms(x: np.ndarray) -> float:
    a = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    x = np.asarray(a, dtype=np.float64).reshape(-1)
    y = np.asarray(b, dtype=np.float64).reshape(-1)
    den = float(np.linalg.norm(x) * np.linalg.norm(y))
    if den <= 1e-12:
        return 0.0 if np.allclose(x, y) else 1.0
    return float(1.0 - np.dot(x, y) / den)


def normalized_words(text: str) -> list[str]:
    clean = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text.lower())
    return clean.split()


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def text_distance(reference: str, candidate: str) -> dict[str, Any]:
    a = normalized_words(reference)
    b = normalized_words(candidate)
    edits = edit_distance(a, b)
    return {
        "reference_words": len(a),
        "candidate_words": len(b),
        "word_edit_distance": edits,
        "normalized_word_edit_distance": float(edits / max(1, len(a))),
    }


def finite_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def transcribe(model: WhisperModel, audio: np.ndarray) -> dict[str, Any]:
    segments_iter, info = model.transcribe(
        audio,
        language="en",
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=False,
        word_timestamps=False,
    )
    segments = []
    for seg in segments_iter:
        segments.append({
            "start": finite_or_none(getattr(seg, "start", None)),
            "end": finite_or_none(getattr(seg, "end", None)),
            "text": str(getattr(seg, "text", "")),
            "avg_logprob": finite_or_none(getattr(seg, "avg_logprob", None)),
            "no_speech_prob": finite_or_none(getattr(seg, "no_speech_prob", None)),
        })
    transcript = "".join(row["text"] for row in segments).strip()
    logps = [row["avg_logprob"] for row in segments if row["avg_logprob"] is not None]
    nsp = [row["no_speech_prob"] for row in segments if row["no_speech_prob"] is not None]
    return {
        "transcript": transcript,
        "segment_count": len(segments),
        "segments": segments,
        "language": str(getattr(info, "language", "")),
        "language_probability": finite_or_none(getattr(info, "language_probability", None)),
        "mean_segment_avg_logprob": float(sum(logps) / len(logps)) if logps else None,
        "mean_no_speech_prob": float(sum(nsp) / len(nsp)) if nsp else None,
        "max_no_speech_prob": max(nsp) if nsp else None,
    }


def encode(model: WhisperModel, audio: np.ndarray) -> dict[str, Any]:
    features = model.feature_extractor(audio)
    if features.ndim != 2 or features.shape[0] != 80:
        raise RuntimeError(f"unexpected feature shape {features.shape}")
    used = min(int(features.shape[-1]), int(model.feature_extractor.nb_max_frames))
    unpadded = np.asarray(features[:, :used], dtype=np.float32)
    padded = np.asarray(pad_or_trim(unpadded, length=ENCODER_INPUT_FRAMES), dtype=np.float32)
    storage = model.encode(padded)
    encoded = np.asarray(storage)
    if encoded.ndim == 2:
        encoded = encoded[np.newaxis, ...]
    encoded = np.asarray(encoded, dtype=np.float32)
    if encoded.ndim != 3 or encoded.shape[0] != 1 or not np.isfinite(encoded).all():
        raise RuntimeError(f"invalid encoder output {encoded.shape}")
    ratio = encoded.shape[1] / float(ENCODER_INPUT_FRAMES)
    active_frames = max(1, min(encoded.shape[1], int(math.ceil(used * ratio))))
    active = encoded[0, :active_frames, :]
    pooled = active.mean(axis=0)
    return {
        "feature_unpadded": unpadded,
        "feature_padded": padded,
        "encoder": encoded,
        "active": active,
        "pooled": pooled,
        "summary": {
            "feature_shape_unpadded": list(unpadded.shape),
            "feature_frames_used": used,
            "feature_sha256_float32": array_hash(padded),
            "feature_mean": float(np.mean(padded)),
            "feature_std": float(np.std(padded)),
            "encoder_shape": list(encoded.shape),
            "encoder_sha256_float32": array_hash(encoded),
            "encoder_output_frames_per_input_frame": float(ratio),
            "active_encoder_frames_inferred": int(active_frames),
            "active_pooled_l2": float(np.linalg.norm(pooled.astype(np.float64))),
        },
    }


def matrix_compare(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    a = np.asarray(reference, dtype=np.float64)
    b = np.asarray(candidate, dtype=np.float64)
    if a.shape != b.shape:
        raise RuntimeError(f"matrix comparison shape mismatch: {a.shape} vs {b.shape}")
    return {
        "flattened_cosine_distance": cosine_distance(a, b),
        "relative_frobenius_difference": float(np.linalg.norm(a - b) / max(float(np.linalg.norm(a)), 1e-12)),
    }


def aligned_frame_compare(reference: np.ndarray, candidate: np.ndarray, *, candidate_offset: int = 0) -> dict[str, Any]:
    if candidate_offset < 0 or candidate_offset >= candidate.shape[0]:
        raise RuntimeError(f"invalid candidate frame offset {candidate_offset}")
    n = min(reference.shape[0], candidate.shape[0] - candidate_offset)
    a = np.asarray(reference[:n], dtype=np.float64)
    b = np.asarray(candidate[candidate_offset:candidate_offset+n], dtype=np.float64)
    an = np.linalg.norm(a, axis=-1)
    bn = np.linalg.norm(b, axis=-1)
    den = an * bn
    dots = np.sum(a * b, axis=-1)
    cos = np.ones(n, dtype=np.float64)
    nz = den > 1e-12
    cos[nz] = dots[nz] / den[nz]
    cos[~nz] = np.where(np.linalg.norm(a[~nz] - b[~nz], axis=-1) <= 1e-12, 1.0, 0.0)
    return {
        "common_frames": int(n),
        "candidate_offset_frames": int(candidate_offset),
        "mean_cosine_distance": float(np.mean(1.0 - cos)),
        "median_cosine_distance": float(np.median(1.0 - cos)),
        "relative_frobenius_difference": float(np.linalg.norm(a - b) / max(float(np.linalg.norm(a)), 1e-12)),
    }


def build_conditions(baseline: np.ndarray) -> list[dict[str, Any]]:
    x = np.asarray(baseline, dtype=np.float32)
    conditions: list[dict[str, Any]] = [{"id": "baseline", "family": "baseline", "level": 1.0, "audio": x, "transform": {"type": "identity"}}]
    for factor in GAIN_FACTORS:
        conditions.append({
            "id": f"gain_{factor:g}", "family": "gain", "level": factor,
            "audio": (x * factor).astype(np.float32), "transform": {"type": "gain", "factor": factor},
        })
    rng = np.random.default_rng(0)
    base_noise = rng.standard_normal(x.shape, dtype=np.float32)
    base_noise /= max(rms(base_noise), 1e-8)
    signal_rms = max(rms(x), 1e-8)
    for snr_db in SNR_DB_VALUES:
        target_noise_rms = signal_rms / (10.0 ** (snr_db / 20.0))
        raw = x + base_noise * target_noise_rms
        clipped = np.clip(raw, -1.0, 1.0).astype(np.float32)
        conditions.append({
            "id": f"snr_{snr_db:g}db", "family": "snr_db", "level": snr_db,
            "audio": clipped,
            "transform": {"type": "additive_white_noise", "snr_db": snr_db, "rng_seed": 0, "clipped_fraction": float(np.mean(np.abs(raw) > 1.0))},
        })
    for seconds in SILENCE_SECONDS:
        prefix = np.zeros(int(round(seconds * SAMPLE_RATE)), dtype=np.float32)
        conditions.append({
            "id": f"silence_{int(round(seconds*1000))}ms", "family": "leading_silence_seconds", "level": seconds,
            "audio": np.concatenate([prefix, x]), "transform": {"type": "prepend_silence", "seconds": seconds},
        })
    return conditions


def first_changed(rows: list[dict[str, Any]], family: str, key_fn) -> dict[str, Any] | None:
    selected = [row for row in rows if row["family"] == family]
    for row in selected:
        if key_fn(row):
            return {"id": row["id"], "level": row["level"]}
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--fixture", type=Path, required=True)
    p.add_argument("--fixture-meta", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("out/audio-dose-response.json"))
    args = p.parse_args()

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started_wall = time.time()
    started = time.perf_counter()
    fixture_meta = json.loads(args.fixture_meta.read_text(encoding="utf-8"))
    observed_fixture_sha = sha256_bytes(args.fixture.read_bytes())
    if observed_fixture_sha != FIXTURE_SHA256 or fixture_meta["sha256"] != FIXTURE_SHA256:
        raise RuntimeError("fixture identity mismatch")
    baseline_audio = decode_audio(str(args.fixture), sampling_rate=SAMPLE_RATE).astype(np.float32)

    t = time.perf_counter()
    model = WhisperModel(str(args.model_dir), device="cpu", compute_type="int8", local_files_only=True)
    model_load_seconds = time.perf_counter() - t

    t = time.perf_counter()
    conditions = build_conditions(baseline_audio)
    baseline_enc = encode(model, baseline_audio)
    baseline_asr = transcribe(model, baseline_audio)
    baseline_text = baseline_asr["transcript"]
    baseline_segments = baseline_asr["segment_count"]
    rows = []
    for spec in conditions:
        audio = spec.pop("audio")
        if spec["id"] == "baseline":
            enc = baseline_enc
            asr = baseline_asr
        else:
            enc = encode(model, audio)
            asr = transcribe(model, audio)

        feature_compare = matrix_compare(baseline_enc["feature_padded"], enc["feature_padded"])
        pooled_distance = cosine_distance(baseline_enc["pooled"], enc["pooled"])
        frame_unaligned = aligned_frame_compare(baseline_enc["active"], enc["active"])
        shift_aware = None
        if spec["family"] == "leading_silence_seconds":
            feature_offset = int(round(float(spec["level"]) / model.feature_extractor.time_per_frame))
            encoder_offset = int(round(feature_offset * enc["summary"]["encoder_output_frames_per_input_frame"]))
            feature_shift = aligned_frame_compare(
                baseline_enc["feature_unpadded"].T,
                enc["feature_unpadded"].T,
                candidate_offset=feature_offset,
            )
            encoder_shift = aligned_frame_compare(
                baseline_enc["active"], enc["active"], candidate_offset=encoder_offset
            )
            shift_aware = {
                "known_seconds": spec["level"],
                "feature_offset_frames": feature_offset,
                "encoder_offset_frames": encoder_offset,
                "feature": feature_shift,
                "encoder": encoder_shift,
            }

        td = text_distance(baseline_text, asr["transcript"])
        rows.append({
            **spec,
            "audio": {
                "samples": int(audio.size),
                "duration_seconds": float(audio.size / SAMPLE_RATE),
                "rms": rms(audio),
                "sha256_float32le": array_hash(np.asarray(audio, dtype="<f4")),
            },
            "feature": {**enc["summary"], **feature_compare},
            "encoder": {
                "active_mean_pooled_cosine_distance_from_baseline": pooled_distance,
                "unaligned": frame_unaligned,
                "shift_aware": shift_aware,
            },
            "decoder": {
                **asr,
                "transcript_distance_from_baseline": td,
                "segment_count_changed": asr["segment_count"] != baseline_segments,
            },
        })

    repeat_enc = encode(model, baseline_audio)
    repeat_asr = transcribe(model, baseline_audio)
    repeat_encoder_hash_equal = repeat_enc["summary"]["encoder_sha256_float32"] == baseline_enc["summary"]["encoder_sha256_float32"]
    repeat_transcript_equal = repeat_asr["transcript"] == baseline_text

    experiment_seconds = time.perf_counter() - t
    derived = {
        "family_levels": {
            "gain": GAIN_FACTORS,
            "snr_db": SNR_DB_VALUES,
            "leading_silence_seconds": SILENCE_SECONDS,
        },
        "first_gain_transcript_change": first_changed(rows, "gain", lambda r: r["decoder"]["transcript_distance_from_baseline"]["word_edit_distance"] > 0),
        "first_snr_transcript_change_in_declared_order": first_changed(rows, "snr_db", lambda r: r["decoder"]["transcript_distance_from_baseline"]["word_edit_distance"] > 0),
        "first_gain_segment_topology_change": first_changed(rows, "gain", lambda r: r["decoder"]["segment_count_changed"]),
        "first_snr_segment_topology_change_in_declared_order": first_changed(rows, "snr_db", lambda r: r["decoder"]["segment_count_changed"]),
        "baseline_repeat_encoder_hash_equal": repeat_encoder_hash_equal,
        "baseline_repeat_transcript_equal": repeat_transcript_equal,
        "portable_method_checks": {
            "gain_dose_response_executed": True,
            "snr_dose_response_executed": True,
            "leading_silence_dose_response_executed": True,
            "feature_surface_observed": True,
            "encoder_surface_observed": True,
            "decoder_surface_observed": True,
            "known_shift_alignment_applied": True,
            "baseline_encoder_repeat_observed": repeat_encoder_hash_equal,
            "baseline_decoder_repeat_observed": repeat_transcript_equal,
        },
    }
    observations = {
        "fixture": fixture_meta,
        "protocol": {
            "sample_rate": SAMPLE_RATE,
            "encoder_feature_frames": ENCODER_INPUT_FRAMES,
            "feature_frame_seconds": float(model.feature_extractor.time_per_frame),
            "encoder_shape": baseline_enc["summary"]["encoder_shape"],
            "full_encoder_tensor_persisted": False,
            "families": ["gain", "snr_db", "leading_silence_seconds"],
        },
        "baseline": {
            "transcript": baseline_text,
            "segment_count": baseline_segments,
            "mean_segment_avg_logprob": baseline_asr["mean_segment_avg_logprob"],
            "max_no_speech_prob": baseline_asr["max_no_speech_prob"],
            "encoder_sha256_float32": baseline_enc["summary"]["encoder_sha256_float32"],
        },
        "conditions": rows,
        "baseline_repeat": {
            "encoder_hash_equal": repeat_encoder_hash_equal,
            "transcript_equal": repeat_transcript_equal,
            "transcript": repeat_asr["transcript"],
        },
    }

    raw_output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    git_sha = os.environ.get("GITHUB_SHA")
    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(started_wall)}")
    bundle = {
        "probe_id": "audio-dose-response-faster-whisper-tiny-v1",
        "instrument": "audio-feature-encoder-decoder-dose-response-suite",
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
        "claim_tags": ["AUDIO", "DOSE_RESPONSE", "ENCODER_REPRESENTATION", "DECODER_SURFACE", "BOUNDARY_SEARCH"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "scope": "single pinned utterance reconnaissance dose-response; not a general ASR robustness curve",
            "first_change_fields": "reported in declared sweep order rather than estimated as continuous physical thresholds",
            "shift_alignment": "uses the known injected silence offset and observed encoder temporal ratio; residual distance may include position effects",
        },
        "known_assumptions": [
            "reuse of one deterministic white-noise realization across SNR levels makes the SNR sweep comparable",
            "baseline-relative transcript edit distance and segment topology are useful decoder response surfaces",
            "feature/encoder distance need not be monotonic for the experiment to be valid",
        ],
        "known_failure_modes": [
            "clipping at low SNR can combine additive-noise and saturation effects; clipped fraction is recorded",
            "one utterance cannot establish population-level transition thresholds",
            "greedy declared dose levels can bracket but not precisely locate a transition boundary",
        ],
        "cost": {
            "model_load_seconds": model_load_seconds,
            "experiment_seconds": experiment_seconds,
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
            "randomness": {"numpy_rng_seed": 0, "beam_size": 1, "temperature": 0.0},
            "raw_input_hash": sha256_json({"fixture": fixture_meta, "gain": GAIN_FACTORS, "snr": SNR_DB_VALUES, "silence": SILENCE_SECONDS}),
            "raw_output_hash": raw_output_hash,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "conditions": len(rows),
        "first_gain_transcript_change": derived["first_gain_transcript_change"],
        "first_snr_transcript_change": derived["first_snr_transcript_change_in_declared_order"],
        "first_snr_segment_change": derived["first_snr_segment_topology_change_in_declared_order"],
        "repeat_encoder_hash_equal": repeat_encoder_hash_equal,
        "repeat_transcript_equal": repeat_transcript_equal,
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
