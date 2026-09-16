#!/usr/bin/env python3
"""Rep 27: approved Faster-Whisper Tiny encoder representation portability.

This rep mirrors Faster-Whisper 1.2.1's transcription protocol up to the encoder:
waveform -> log-Mel features -> current chunk -> pad/trim to 3000 frames -> encode.
It summarizes encoder geometry at source and does not persist the full representation.
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
INPUT_ENCODER_FRAMES = 3000


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def array_hash(x: np.ndarray) -> str:
    a = np.ascontiguousarray(x)
    return sha256_bytes(a.tobytes(order="C"))


def rms(audio: np.ndarray) -> float:
    x = np.asarray(audio, dtype=np.float64)
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    x = np.asarray(a, dtype=np.float64).reshape(-1)
    y = np.asarray(b, dtype=np.float64).reshape(-1)
    den = float(np.linalg.norm(x) * np.linalg.norm(y))
    if den <= 1e-12:
        return 0.0 if np.allclose(x, y) else 1.0
    return float(1.0 - np.dot(x, y) / den)


def build_variants(baseline: np.ndarray) -> list[dict[str, Any]]:
    x = np.asarray(baseline, dtype=np.float32)
    rng = np.random.default_rng(0)
    signal_rms = max(rms(x), 1e-8)
    noise = rng.standard_normal(x.shape, dtype=np.float32)
    noise = noise / max(rms(noise), 1e-8) * (signal_rms / 10.0)
    noisy = np.clip(x + noise, -1.0, 1.0).astype(np.float32)
    silence_prefix = np.zeros(int(0.5 * SAMPLE_RATE), dtype=np.float32)
    t = np.arange(x.size, dtype=np.float32) / SAMPLE_RATE
    tone = (0.1 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    silence = np.zeros_like(x, dtype=np.float32)
    return [
        {"id": "baseline", "kind": "speech", "audio": x, "transform": {"type": "identity"}},
        {"id": "quiet_x0_25", "kind": "speech_perturbation", "audio": (x * 0.25).astype(np.float32), "transform": {"type": "gain", "factor": 0.25}},
        {"id": "prepend_silence_500ms", "kind": "speech_perturbation", "audio": np.concatenate([silence_prefix, x]), "transform": {"type": "prepend_silence", "seconds": 0.5}},
        {"id": "noise_20db", "kind": "speech_perturbation", "audio": noisy, "transform": {"type": "additive_white_noise", "snr_db": 20.0, "rng_seed": 0}},
        {"id": "silence_control", "kind": "no_speech_control", "audio": silence, "transform": {"type": "silence", "duration_matches_baseline": True}},
        {"id": "tone_440hz_control", "kind": "no_speech_control", "audio": tone, "transform": {"type": "sine_tone", "frequency_hz": 440.0, "amplitude": 0.1, "duration_matches_baseline": True}},
    ]


def quantiles(values: np.ndarray) -> dict[str, float]:
    x = np.asarray(values, dtype=np.float64).reshape(-1)
    q = np.quantile(x, [0.0, 0.25, 0.5, 0.75, 1.0])
    return {k: float(v) for k, v in zip(("min", "q25", "median", "q75", "max"), q)}


def encode_one(model: WhisperModel, audio: np.ndarray) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    features = model.feature_extractor(audio)
    if features.ndim != 2 or features.shape[0] != 80:
        raise RuntimeError(f"unexpected log-Mel shape: {features.shape}")
    actual_feature_frames = min(int(features.shape[-1]), int(model.feature_extractor.nb_max_frames))
    segment = features[:, :actual_feature_frames]
    padded = pad_or_trim(segment, length=INPUT_ENCODER_FRAMES)
    if padded.shape != (80, INPUT_ENCODER_FRAMES):
        raise RuntimeError(f"unexpected padded log-Mel shape: {padded.shape}")

    storage = model.encode(padded)
    encoded = np.asarray(storage)
    if encoded.ndim == 2:
        encoded = encoded[np.newaxis, ...]
    if encoded.ndim != 3 or encoded.shape[0] != 1:
        raise RuntimeError(f"unexpected encoder output shape: {encoded.shape}")
    encoded = np.asarray(encoded, dtype=np.float32)
    if not np.isfinite(encoded).all():
        raise RuntimeError("non-finite encoder output")

    output_frames = int(encoded.shape[1])
    ratio = output_frames / float(INPUT_ENCODER_FRAMES)
    active_output_frames = max(1, min(output_frames, int(math.ceil(actual_feature_frames * ratio))))
    active = encoded[0, :active_output_frames, :]
    pooled = active.mean(axis=0)
    frame_l2 = np.linalg.norm(active.astype(np.float64), axis=-1)

    summary = {
        "feature_shape_unpadded": list(features.shape),
        "feature_frames_used": actual_feature_frames,
        "feature_shape_encoder_input": list(padded.shape),
        "feature_sha256_float32": array_hash(np.asarray(padded, dtype=np.float32)),
        "feature_mean": float(np.mean(padded)),
        "feature_std": float(np.std(padded)),
        "encoder_shape": list(encoded.shape),
        "encoder_dtype": str(encoded.dtype),
        "encoder_sha256_float32": array_hash(encoded),
        "encoder_output_frames_per_input_frame": ratio,
        "active_encoder_frames_inferred": active_output_frames,
        "active_pooled_l2": float(np.linalg.norm(pooled.astype(np.float64))),
        "active_pooled_mean": float(np.mean(pooled)),
        "active_pooled_std": float(np.std(pooled)),
        "active_frame_l2_quantiles": quantiles(frame_l2),
    }
    return summary, pooled.astype(np.float32), active


def aligned_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    n = min(reference.shape[0], candidate.shape[0])
    ref = np.asarray(reference[:n], dtype=np.float64)
    cand = np.asarray(candidate[:n], dtype=np.float64)
    ref_norm = np.linalg.norm(ref, axis=-1)
    cand_norm = np.linalg.norm(cand, axis=-1)
    den = ref_norm * cand_norm
    dots = np.sum(ref * cand, axis=-1)
    cosine = np.ones(n, dtype=np.float64)
    nonzero = den > 1e-12
    cosine[nonzero] = dots[nonzero] / den[nonzero]
    cosine[~nonzero] = np.where(np.linalg.norm(ref[~nonzero] - cand[~nonzero], axis=-1) <= 1e-12, 1.0, 0.0)
    diff = ref - cand
    per_frame_l2 = np.linalg.norm(diff, axis=-1)
    ref_frob = float(np.linalg.norm(ref))
    return {
        "common_active_frames": int(n),
        "mean_frame_cosine_distance": float(np.mean(1.0 - cosine)),
        "median_frame_cosine_distance": float(np.median(1.0 - cosine)),
        "mean_frame_l2_difference": float(np.mean(per_frame_l2)),
        "relative_frobenius_difference": float(np.linalg.norm(diff) / max(ref_frob, 1e-12)),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--fixture", type=Path, required=True)
    p.add_argument("--fixture-meta", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("out/audio-encoder-representation.json"))
    args = p.parse_args()

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started_wall = time.time()
    started = time.perf_counter()

    fixture_meta = json.loads(args.fixture_meta.read_text(encoding="utf-8"))
    fixture_bytes = args.fixture.read_bytes()
    observed_fixture_sha = sha256_bytes(fixture_bytes)
    if observed_fixture_sha != FIXTURE_SHA256 or fixture_meta["sha256"] != FIXTURE_SHA256:
        raise RuntimeError(f"fixture hash mismatch: {observed_fixture_sha}")
    baseline_audio = decode_audio(str(args.fixture), sampling_rate=SAMPLE_RATE).astype(np.float32)
    if baseline_audio.ndim != 1 or not np.isfinite(baseline_audio).all():
        raise RuntimeError("invalid decoded baseline audio")

    t = time.perf_counter()
    model = WhisperModel(str(args.model_dir), device="cpu", compute_type="int8", local_files_only=True)
    model_load_seconds = time.perf_counter() - t

    t = time.perf_counter()
    rows = []
    pooled_by_id: dict[str, np.ndarray] = {}
    active_by_id: dict[str, np.ndarray] = {}
    for spec in build_variants(baseline_audio):
        audio = spec.pop("audio")
        summary, pooled, active = encode_one(model, audio)
        row = {
            **spec,
            "audio": {
                "sample_rate": SAMPLE_RATE,
                "samples": int(audio.size),
                "duration_seconds": float(audio.size / SAMPLE_RATE),
                "rms": rms(audio),
                "sha256_float32le": array_hash(np.asarray(audio, dtype="<f4")),
            },
            "representation": summary,
        }
        rows.append(row)
        pooled_by_id[row["id"]] = pooled
        active_by_id[row["id"]] = active

    baseline_pooled = pooled_by_id["baseline"]
    baseline_active = active_by_id["baseline"]
    for row in rows:
        pid = row["id"]
        row["geometry_from_baseline"] = {
            "active_mean_pooled_cosine_distance": cosine_distance(baseline_pooled, pooled_by_id[pid]),
            **aligned_metrics(baseline_active, active_by_id[pid]),
        }

    repeat_summary, repeat_pooled, repeat_active = encode_one(model, baseline_audio)
    repeat_hash_equal = repeat_summary["encoder_sha256_float32"] == rows[0]["representation"]["encoder_sha256_float32"]
    repeat_pooled_distance = cosine_distance(baseline_pooled, repeat_pooled)
    repeat_aligned = aligned_metrics(baseline_active, repeat_active)

    experiment_seconds = time.perf_counter() - t
    derived = {
        "pooled_cosine_distance_from_baseline": {row["id"]: row["geometry_from_baseline"]["active_mean_pooled_cosine_distance"] for row in rows},
        "mean_aligned_frame_cosine_distance_from_baseline": {row["id"]: row["geometry_from_baseline"]["mean_frame_cosine_distance"] for row in rows},
        "relative_frobenius_difference_from_baseline": {row["id"]: row["geometry_from_baseline"]["relative_frobenius_difference"] for row in rows},
        "baseline_repeat_encoder_hash_equal": repeat_hash_equal,
        "baseline_repeat_pooled_cosine_distance": repeat_pooled_distance,
        "baseline_repeat_mean_frame_cosine_distance": repeat_aligned["mean_frame_cosine_distance"],
        "portable_instrument_checks": {
            "approved_foundry_oci_identity": True,
            "exact_faster_whisper_feature_protocol_mirrored": True,
            "log_mel_features_observed": True,
            "encoder_storage_view_observed": True,
            "encoder_tensor_converted_locally": True,
            "active_time_pooling_observed": True,
            "aligned_frame_geometry_observed": True,
            "speech_and_no_speech_controls_observed": True,
            "deterministic_encoder_repeat_observed": repeat_hash_equal,
        },
    }
    observations = {
        "fixture": fixture_meta,
        "protocol": {
            "faster_whisper_version": "1.2.1",
            "feature_extractor": "WhisperModel.feature_extractor(waveform)",
            "chunk": "first feature chunk up to nb_max_frames",
            "pad_or_trim_frames": INPUT_ENCODER_FRAMES,
            "encoder_call": "WhisperModel.encode(padded_log_mel)",
            "full_encoder_tensor_persisted": False,
            "reduction": "active-prefix mean pooling plus aligned-frame summary metrics",
        },
        "variants": rows,
        "baseline_repeat": {
            "representation": repeat_summary,
            "encoder_hash_equal": repeat_hash_equal,
            "pooled_cosine_distance": repeat_pooled_distance,
            "aligned_metrics": repeat_aligned,
        },
    }

    raw_output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    git_sha = os.environ.get("GITHUB_SHA")
    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(started_wall)}")
    bundle = {
        "probe_id": "audio-encoder-representation-faster-whisper-tiny-v1",
        "instrument": "audio-logmel-encoder-representation-geometry-suite",
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
            "verification_ref": "digest-pinned approved Foundry hydration with bundle/file verification and offline local reuse",
            "tokenizer_artifact": None,
        },
        "access_tier": "A2",
        "evidence_level": "REPRODUCED",
        "claim_tags": ["AUDIO", "ENCODER_REPRESENTATION", "REPRESENTATION_GEOMETRY", "PERTURBATION_SURFACE"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "scope": "encoder-representation portability on one pinned speech fixture and deterministic controls; not a general acoustic representation benchmark",
            "active_frame_inference": "active encoder length is inferred from observed output/input frame ratio after exact 3000-frame encoder padding",
            "pooling": "mean pooling is descriptive and has not earned status as a preferred Whisper representation metric",
        },
        "known_assumptions": [
            "mirroring Faster-Whisper's first-chunk log-Mel/pad/encode protocol makes encoder comparisons protocol-faithful for this <30s fixture",
            "active-prefix mean pooling and aligned-frame distance are adequate reconnaissance summaries",
            "full encoder tensors need not be persisted to preserve the first-order geometric evidence",
        ],
        "known_failure_modes": [
            "leading-silence perturbation shifts temporal alignment, so aligned-frame metrics intentionally conflate content shift and representation change",
            "mean pooling can hide localized temporal changes",
            "CTranslate2 exposes the final encoder output but not per-layer encoder hidden states through this public surface",
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
            "randomness": {"numpy_rng_seed": 0, "sampling": False},
            "raw_input_hash": sha256_json({"fixture": fixture_meta, "variants": [row["id"] for row in rows], "protocol": observations["protocol"]}),
            "raw_output_hash": raw_output_hash,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "encoder_shape": rows[0]["representation"]["encoder_shape"],
        "pooled_distances": derived["pooled_cosine_distance_from_baseline"],
        "frame_distances": derived["mean_aligned_frame_cosine_distance_from_baseline"],
        "repeat_hash_equal": repeat_hash_equal,
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
