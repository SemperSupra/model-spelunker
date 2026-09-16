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
from pathlib import Path
from typing import Any

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio, pad_or_trim

LOGICAL_ID = "asr/faster-whisper/tiny"
UPSTREAM_REPO = "Systran/faster-whisper-tiny"
UPSTREAM_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
FOUNDRY_DIGEST = "sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
DATASET_REPO = "PolyAI/minds14"
DATASET_REVISION = "40ce77cb32a384e4d50a568e1ec39ac804019d33"
EXPECTED_CONFIGS = {"de-DE": "de", "en-US": "en", "fr-FR": "fr"}
SAMPLE_RATE = 16000
ENCODER_INPUT_FRAMES = 3000
SNR_LEVELS = (20.0, 10.0)


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def array_hash(x: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(x).tobytes(order="C"))


def rms(x: np.ndarray) -> float:
    a = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def normalize_words(text: str) -> list[str]:
    clean = "".join(ch.casefold() if (ch.isalnum() or ch.isspace()) else " " for ch in text)
    return clean.split()


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def text_metrics(reference: str, candidate: str) -> dict[str, Any]:
    a, b = normalize_words(reference), normalize_words(candidate)
    edits = edit_distance(a, b)
    return {
        "reference_words": len(a),
        "candidate_words": len(b),
        "word_edit_distance": edits,
        "wer": float(edits / max(1, len(a))),
        "exact_normalized_match": a == b,
    }


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    x, y = np.asarray(a, dtype=np.float64).reshape(-1), np.asarray(b, dtype=np.float64).reshape(-1)
    den = float(np.linalg.norm(x) * np.linalg.norm(y))
    if den <= 1e-12:
        return 0.0 if np.allclose(x, y) else 1.0
    return float(1.0 - np.dot(x, y) / den)


def frame_compare(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    n = min(a.shape[0], b.shape[0])
    x, y = np.asarray(a[:n], dtype=np.float64), np.asarray(b[:n], dtype=np.float64)
    xn, yn = np.linalg.norm(x, axis=-1), np.linalg.norm(y, axis=-1)
    den = xn * yn
    dots = np.sum(x * y, axis=-1)
    cos = np.ones(n, dtype=np.float64)
    nz = den > 1e-12
    cos[nz] = dots[nz] / den[nz]
    cos[~nz] = np.where(np.linalg.norm(x[~nz] - y[~nz], axis=-1) <= 1e-12, 1.0, 0.0)
    return {
        "common_frames": int(n),
        "mean_cosine_distance": float(np.mean(1.0 - cos)),
        "relative_frobenius_difference": float(np.linalg.norm(x - y) / max(float(np.linalg.norm(x)), 1e-12)),
    }


def encode(model: WhisperModel, audio: np.ndarray) -> dict[str, Any]:
    features = model.feature_extractor(audio)
    used = min(int(features.shape[-1]), int(model.feature_extractor.nb_max_frames))
    unpadded = np.asarray(features[:, :used], dtype=np.float32)
    padded = np.asarray(pad_or_trim(unpadded, length=ENCODER_INPUT_FRAMES), dtype=np.float32)
    encoded = np.asarray(model.encode(padded), dtype=np.float32)
    if encoded.ndim == 2:
        encoded = encoded[np.newaxis, ...]
    if encoded.ndim != 3 or encoded.shape[0] != 1 or not np.isfinite(encoded).all():
        raise RuntimeError(f"invalid encoder shape {encoded.shape}")
    ratio = encoded.shape[1] / float(ENCODER_INPUT_FRAMES)
    active_frames = max(1, min(encoded.shape[1], int(math.ceil(used * ratio))))
    active = encoded[0, :active_frames, :]
    pooled = active.mean(axis=0)
    return {
        "feature_padded": padded,
        "active": active,
        "pooled": pooled,
        "summary": {
            "feature_frames_used": used,
            "feature_shape_encoder_input": list(padded.shape),
            "feature_sha256_float32": array_hash(padded),
            "encoder_shape": list(encoded.shape),
            "encoder_sha256_float32": array_hash(encoded),
            "active_encoder_frames_inferred": active_frames,
            "active_pooled_l2": float(np.linalg.norm(pooled.astype(np.float64))),
        },
    }


def transcribe(model: WhisperModel, audio: np.ndarray) -> dict[str, Any]:
    segments_iter, info = model.transcribe(
        audio,
        language=None,
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=False,
        word_timestamps=False,
    )
    segments = list(segments_iter)
    transcript = "".join(seg.text for seg in segments).strip()
    logps = [float(seg.avg_logprob) for seg in segments if math.isfinite(float(seg.avg_logprob))]
    nsp = [float(seg.no_speech_prob) for seg in segments if math.isfinite(float(seg.no_speech_prob))]
    return {
        "transcript": transcript,
        "segment_count": len(segments),
        "detected_language": str(info.language),
        "language_probability": float(info.language_probability),
        "mean_segment_avg_logprob": float(sum(logps) / len(logps)) if logps else None,
        "max_no_speech_prob": max(nsp) if nsp else None,
    }


def noisy(audio: np.ndarray, snr_db: float, seed: int) -> tuple[np.ndarray, float]:
    rng = np.random.default_rng(seed)
    direction = rng.standard_normal(audio.shape, dtype=np.float32)
    direction /= max(rms(direction), 1e-8)
    target = max(rms(audio), 1e-8) / (10.0 ** (snr_db / 20.0))
    raw = audio + direction * target
    clipped = np.clip(raw, -1.0, 1.0).astype(np.float32)
    return clipped, float(np.mean(np.abs(raw) > 1.0))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--panel-manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("out/audio-multilingual-panel.json"))
    args = p.parse_args()

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started = time.perf_counter()
    panel = json.loads(args.panel_manifest.read_text(encoding="utf-8"))
    if panel["dataset"]["repository"] != DATASET_REPO or panel["dataset"]["exact_revision"] != DATASET_REVISION:
        raise RuntimeError("panel dataset identity mismatch")
    if panel["dataset"]["speaker_claims_permitted"] is not False:
        raise RuntimeError("speaker claims must remain disabled")

    t = time.perf_counter()
    model = WhisperModel(str(args.model_dir), device="cpu", compute_type="int8", local_files_only=True)
    model_load_seconds = time.perf_counter() - t

    t = time.perf_counter()
    sample_results = []
    for sample_index, sample in enumerate(panel["samples"]):
        config = sample["config"]
        expected_language = sample["expected_language"]
        if EXPECTED_CONFIGS.get(config) != expected_language:
            raise RuntimeError(f"unexpected language mapping {config}/{expected_language}")
        audio = decode_audio(sample["local_audio_path"], sampling_rate=SAMPLE_RATE).astype(np.float32)
        base_enc = encode(model, audio)
        base_asr = transcribe(model, audio)
        conditions = []

        def add_condition(cid: str, condition_audio: np.ndarray, enc: dict[str, Any], asr: dict[str, Any], clipped_fraction: float, snr_db: float | None) -> None:
            if cid == "baseline":
                pooled_distance = 0.0
                frames = {"common_frames": base_enc["active"].shape[0], "mean_cosine_distance": 0.0, "relative_frobenius_difference": 0.0}
                feature_distance = 0.0
                feature_frob = 0.0
            else:
                pooled_distance = cosine_distance(base_enc["pooled"], enc["pooled"])
                frames = frame_compare(base_enc["active"], enc["active"])
                feature_distance = cosine_distance(base_enc["feature_padded"], enc["feature_padded"])
                feature_frob = float(np.linalg.norm(base_enc["feature_padded"].astype(np.float64) - enc["feature_padded"].astype(np.float64)) / max(float(np.linalg.norm(base_enc["feature_padded"].astype(np.float64))), 1e-12))
            conditions.append({
                "id": cid,
                "snr_db": snr_db,
                "audio": {
                    "samples": int(condition_audio.size),
                    "duration_seconds": float(condition_audio.size / SAMPLE_RATE),
                    "rms": rms(condition_audio),
                    "sha256_float32le": array_hash(np.asarray(condition_audio, dtype="<f4")),
                    "clipped_fraction": clipped_fraction,
                },
                "representation": {
                    **enc["summary"],
                    "feature_cosine_distance_from_baseline": feature_distance,
                    "feature_relative_frobenius_from_baseline": feature_frob,
                    "pooled_encoder_cosine_distance_from_baseline": pooled_distance,
                    "frame_geometry_from_baseline": frames,
                },
                "decoder": {
                    **asr,
                    "language_matches_expected": asr["detected_language"] == expected_language,
                    "reference_text_metrics": text_metrics(sample["transcription"], asr["transcript"]),
                    "baseline_transcript_metrics": text_metrics(base_asr["transcript"], asr["transcript"]),
                },
            })

        add_condition("baseline", audio, base_enc, base_asr, 0.0, None)
        seed = int(hashlib.sha256(sample["sample_id"].encode()).hexdigest()[:8], 16)
        for snr_db in SNR_LEVELS:
            n_audio, clipped_fraction = noisy(audio, snr_db, seed)
            add_condition(f"noise_{int(snr_db)}db", n_audio, encode(model, n_audio), transcribe(model, n_audio), clipped_fraction, snr_db)

        sample_results.append({
            "sample": sample,
            "noise_seed": seed,
            "conditions": conditions,
        })

    experiment_seconds = time.perf_counter() - t
    by_language: dict[str, Any] = {}
    unchanged_with_moved_representation = {"noise_20db": 0, "noise_10db": 0}
    for config, expected_language in EXPECTED_CONFIGS.items():
        group = [r for r in sample_results if r["sample"]["config"] == config]
        stats = {}
        for cid in ("baseline", "noise_20db", "noise_10db"):
            rows = [next(c for c in r["conditions"] if c["id"] == cid) for r in group]
            stats[cid] = {
                "mean_reference_wer": float(np.mean([c["decoder"]["reference_text_metrics"]["wer"] for c in rows])),
                "detected_language_matches": sum(1 for c in rows if c["decoder"]["language_matches_expected"]),
                "mean_pooled_encoder_cosine_distance_from_baseline": float(np.mean([c["representation"]["pooled_encoder_cosine_distance_from_baseline"] for c in rows])),
                "mean_frame_encoder_cosine_distance_from_baseline": float(np.mean([c["representation"]["frame_geometry_from_baseline"]["mean_cosine_distance"] for c in rows])),
            }
        by_language[config] = {"expected_language": expected_language, **stats}

    for result in sample_results:
        for cid in ("noise_20db", "noise_10db"):
            c = next(x for x in result["conditions"] if x["id"] == cid)
            if c["decoder"]["baseline_transcript_metrics"]["word_edit_distance"] == 0 and c["representation"]["frame_geometry_from_baseline"]["mean_cosine_distance"] > 1e-6:
                unchanged_with_moved_representation[cid] += 1

    observations = {
        "panel": panel,
        "protocol": {
            "sample_rate": SAMPLE_RATE,
            "snr_levels_db": list(SNR_LEVELS),
            "beam_size": 1,
            "temperature": 0.0,
            "language_mode": "automatic detection per condition",
            "full_encoder_tensor_persisted": False,
            "speaker_identity_available": False,
        },
        "samples": sample_results,
    }
    derived = {
        "per_language": by_language,
        "unchanged_transcript_with_moved_representation": unchanged_with_moved_representation,
        "panel_counts": {
            "samples": len(sample_results),
            "languages": len(EXPECTED_CONFIGS),
            "conditions": sum(len(x["conditions"]) for x in sample_results),
        },
        "portable_method_checks": {
            "real_multilingual_audio_consumed": True,
            "dataset_revision_pinned": True,
            "speaker_claims_suppressed": True,
            "baseline_20db_10db_executed_for_every_sample": True,
            "feature_encoder_decoder_surfaces_recorded": True,
        },
    }
    raw_output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    git_sha = os.environ.get("GITHUB_SHA")
    bundle = {
        "probe_id": "audio-multilingual-generalization-faster-whisper-tiny-v1",
        "instrument": "multilingual-audio-feature-encoder-decoder-generalization-suite",
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
            "foundry_record_ref": "SemperSupra/model-artifact-foundry@6622753fd5914be87fb1b6d987ceb7cae46c7ff5:catalog/approved.json",
            "consumer_selection_ref": f"model-spelunker@{git_sha}" if git_sha else None,
            "verified": True,
            "verification_ref": "digest-pinned approved Foundry hydration with offline local reuse",
            "tokenizer_artifact": None,
        },
        "access_tier": "A2",
        "evidence_level": "REPRODUCED",
        "claim_tags": ["AUDIO", "MULTILINGUAL", "GENERALIZATION", "ENCODER_REPRESENTATION", "ROBUSTNESS_SURFACE"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "scope": "six fixed utterances from three MInDS-14 language varieties; not a population benchmark",
            "speaker_identity": "dataset parquet does not expose speaker identity; no speaker-level inference is made",
            "noise": "one deterministic noise direction per utterance is reused across SNR levels",
        },
        "known_assumptions": [
            "two distinct intent classes per language provide useful utterance/content diversity",
            "automatic language detection plus transcription is an appropriate end-to-end ASR surface",
        ],
        "known_failure_modes": [
            "small sample size cannot establish language-level accuracy or robustness",
            "reference transcript normalization is intentionally simple and may over- or under-count language-specific tokenization errors",
            "speaker diversity is unknown",
        ],
        "cost": {
            "model_load_seconds": model_load_seconds,
            "experiment_seconds": experiment_seconds,
            "total_script_seconds": time.perf_counter() - started,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        },
        "provenance": {
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
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
            "randomness": {"noise_seed_policy": "sha256(sample_id) first 32 bits", "beam_size": 1, "temperature": 0.0},
            "raw_input_hash": sha256_json(panel),
            "raw_output_hash": raw_output_hash,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "samples": len(sample_results),
        "conditions": derived["panel_counts"]["conditions"],
        "unchanged_with_moved_representation": unchanged_with_moved_representation,
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
