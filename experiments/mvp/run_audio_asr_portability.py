#!/usr/bin/env python3
"""Rep 26: audio/ASR perturbation portability using approved Faster-Whisper Tiny.

This rep stays at the functional ASR surface: transcript sequences, segment timing,
average log-probability, no-speech probability, and deterministic audio contrasts.
It does not claim encoder-level localization or benchmark-quality ASR accuracy.
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
from faster_whisper.audio import decode_audio

LOGICAL_ID = "asr/faster-whisper/tiny"
UPSTREAM_REPO = "Systran/faster-whisper-tiny"
UPSTREAM_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
FOUNDRY_DIGEST = "sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
FOUNDRY_CATALOG_REF = "SemperSupra/model-artifact-foundry@6622753fd5914be87fb1b6d987ceb7cae46c7ff5:catalog/approved.json"
SAMPLE_RATE = 16000
EXPECTED_PHRASES = ["my fellow americans", "your country", "do for you"]


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def audio_sha256(audio: np.ndarray) -> str:
    x = np.asarray(audio, dtype="<f4")
    return sha256_bytes(x.tobytes(order="C"))


def rms(audio: np.ndarray) -> float:
    x = np.asarray(audio, dtype=np.float64)
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def normalize_text(text: str) -> list[str]:
    chars = []
    for ch in text.lower():
        chars.append(ch if ch.isalnum() or ch.isspace() else " ")
    return "".join(chars).split()


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def transcript_distance(reference: str, candidate: str) -> dict[str, Any]:
    ref = normalize_text(reference)
    cand = normalize_text(candidate)
    edits = edit_distance(ref, cand)
    return {
        "reference_words": len(ref),
        "candidate_words": len(cand),
        "word_edit_distance": edits,
        "normalized_word_edit_distance": float(edits / max(1, len(ref))),
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
    for s in segments_iter:
        segments.append({
            "id": int(getattr(s, "id", len(segments))),
            "seek": int(getattr(s, "seek", 0)),
            "start": finite_or_none(getattr(s, "start", None)),
            "end": finite_or_none(getattr(s, "end", None)),
            "text": str(getattr(s, "text", "")),
            "avg_logprob": finite_or_none(getattr(s, "avg_logprob", None)),
            "compression_ratio": finite_or_none(getattr(s, "compression_ratio", None)),
            "no_speech_prob": finite_or_none(getattr(s, "no_speech_prob", None)),
            "temperature": finite_or_none(getattr(s, "temperature", None)),
        })
    transcript = "".join(row["text"] for row in segments).strip()
    avg_logprobs = [row["avg_logprob"] for row in segments if row["avg_logprob"] is not None]
    no_speech = [row["no_speech_prob"] for row in segments if row["no_speech_prob"] is not None]
    compression = [row["compression_ratio"] for row in segments if row["compression_ratio"] is not None]
    return {
        "transcript": transcript,
        "segments": segments,
        "segment_count": len(segments),
        "language": str(getattr(info, "language", "")),
        "language_probability": finite_or_none(getattr(info, "language_probability", None)),
        "duration": finite_or_none(getattr(info, "duration", None)),
        "duration_after_vad": finite_or_none(getattr(info, "duration_after_vad", None)),
        "mean_segment_avg_logprob": float(sum(avg_logprobs) / len(avg_logprobs)) if avg_logprobs else None,
        "mean_no_speech_prob": float(sum(no_speech) / len(no_speech)) if no_speech else None,
        "max_no_speech_prob": max(no_speech) if no_speech else None,
        "mean_compression_ratio": float(sum(compression) / len(compression)) if compression else None,
    }


def build_variants(baseline: np.ndarray) -> list[dict[str, Any]]:
    x = np.asarray(baseline, dtype=np.float32)
    rng = np.random.default_rng(0)
    sig_rms = max(rms(x), 1e-8)
    noise = rng.standard_normal(x.shape, dtype=np.float32)
    noise = noise / max(rms(noise), 1e-8) * (sig_rms / 10.0)  # 20 dB SNR
    noisy = np.clip(x + noise, -1.0, 1.0).astype(np.float32)
    silence_prefix = np.zeros(int(0.5 * SAMPLE_RATE), dtype=np.float32)
    tone_t = np.arange(x.size, dtype=np.float32) / SAMPLE_RATE
    tone = (0.1 * np.sin(2 * np.pi * 440.0 * tone_t)).astype(np.float32)
    silence = np.zeros_like(x, dtype=np.float32)
    return [
        {"id": "baseline", "kind": "speech", "audio": x, "transform": {"type": "identity"}},
        {"id": "quiet_x0_25", "kind": "speech_perturbation", "audio": (x * 0.25).astype(np.float32), "transform": {"type": "gain", "factor": 0.25}},
        {"id": "prepend_silence_500ms", "kind": "speech_perturbation", "audio": np.concatenate([silence_prefix, x]), "transform": {"type": "prepend_silence", "seconds": 0.5}},
        {"id": "noise_20db", "kind": "speech_perturbation", "audio": noisy, "transform": {"type": "additive_white_noise", "snr_db": 20.0, "rng_seed": 0}},
        {"id": "silence_control", "kind": "no_speech_control", "audio": silence, "transform": {"type": "silence", "duration_matches_baseline": True}},
        {"id": "tone_440hz_control", "kind": "no_speech_control", "audio": tone, "transform": {"type": "sine_tone", "frequency_hz": 440.0, "amplitude": 0.1, "duration_matches_baseline": True}},
    ]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--fixture", type=Path, required=True)
    p.add_argument("--fixture-meta", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("out/audio-asr-portability.json"))
    args = p.parse_args()

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started_wall = time.time()
    started = time.perf_counter()

    fixture_meta = json.loads(args.fixture_meta.read_text(encoding="utf-8"))
    fixture_bytes = args.fixture.read_bytes()
    observed_fixture_sha = sha256_bytes(fixture_bytes)
    if fixture_meta["sha256"] != observed_fixture_sha:
        raise RuntimeError("fixture metadata/hash mismatch")

    baseline_audio = decode_audio(str(args.fixture), sampling_rate=SAMPLE_RATE).astype(np.float32)
    if baseline_audio.ndim != 1 or baseline_audio.size < SAMPLE_RATE:
        raise RuntimeError(f"unexpected decoded fixture shape: {baseline_audio.shape}")
    if not np.isfinite(baseline_audio).all():
        raise RuntimeError("non-finite decoded fixture")

    t = time.perf_counter()
    model = WhisperModel(str(args.model_dir), device="cpu", compute_type="int8", local_files_only=True)
    model_load_seconds = time.perf_counter() - t

    t = time.perf_counter()
    variants = build_variants(baseline_audio)
    rows = []
    baseline_result = None
    for variant in variants:
        audio = variant.pop("audio")
        result = transcribe(model, audio)
        row = {
            **variant,
            "audio": {
                "sample_rate": SAMPLE_RATE,
                "samples": int(audio.size),
                "duration_seconds": float(audio.size / SAMPLE_RATE),
                "rms": rms(audio),
                "peak_abs": float(np.max(np.abs(audio))) if audio.size else 0.0,
                "sha256_float32le": audio_sha256(audio),
            },
            "result": result,
        }
        rows.append(row)
        if row["id"] == "baseline":
            baseline_result = result
    assert baseline_result is not None

    repeat_baseline = transcribe(model, baseline_audio)
    repeat_exact = repeat_baseline["transcript"] == baseline_result["transcript"]
    repeat_logprob_delta = None
    a = baseline_result["mean_segment_avg_logprob"]
    b = repeat_baseline["mean_segment_avg_logprob"]
    if a is not None and b is not None:
        repeat_logprob_delta = abs(a - b)

    baseline_text = baseline_result["transcript"]
    for row in rows:
        row["transcript_distance_from_baseline"] = transcript_distance(baseline_text, row["result"]["transcript"])
        low = row["result"]["transcript"].lower()
        row["expected_phrase_presence"] = {phrase: phrase in low for phrase in EXPECTED_PHRASES}

    experiment_seconds = time.perf_counter() - t
    speech_rows = [row for row in rows if row["kind"] != "no_speech_control"]
    control_rows = [row for row in rows if row["kind"] == "no_speech_control"]
    derived = {
        "baseline_expected_phrase_count": sum(rows[0]["expected_phrase_presence"].values()),
        "speech_variant_normalized_word_edit_distances": {
            row["id"]: row["transcript_distance_from_baseline"]["normalized_word_edit_distance"] for row in speech_rows
        },
        "no_speech_control_transcript_word_counts": {
            row["id"]: len(normalize_text(row["result"]["transcript"])) for row in control_rows
        },
        "no_speech_control_max_no_speech_prob": {
            row["id"]: row["result"]["max_no_speech_prob"] for row in control_rows
        },
        "baseline_repeat_exact_transcript": repeat_exact,
        "baseline_repeat_mean_logprob_abs_delta": repeat_logprob_delta,
        "portable_instrument_checks": {
            "approved_foundry_oci_identity": True,
            "pinned_real_speech_fixture": True,
            "audio_waveform_perturbations_executed": True,
            "sequence_transcripts_observed": True,
            "segment_timing_observed": True,
            "segment_logprob_surface_observed": True,
            "no_speech_probability_surface_observed": True,
            "speech_and_no_speech_controls_observed": True,
            "deterministic_baseline_repeat_observed": True,
        },
    }
    observations = {
        "fixture": fixture_meta,
        "sample_rate": SAMPLE_RATE,
        "variants": rows,
        "baseline_repeat": repeat_baseline,
    }

    git_sha = os.environ.get("GITHUB_SHA")
    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(started_wall)}")
    raw_output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    bundle = {
        "probe_id": "audio-asr-portability-faster-whisper-tiny-v1",
        "instrument": "audio-transcript-confidence-and-perturbation-suite",
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
            "verification_ref": "digest-pinned approved Foundry hydration with bundle/file verification and local offline reuse",
            "tokenizer_artifact": None,
        },
        "access_tier": "A1",
        "evidence_level": "REPRODUCED",
        "claim_tags": ["AUDIO", "ASR", "PERTURBATION_SURFACE", "CONFIDENCE_SURFACE"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "scope": "instrument/model-class portability on one pinned speech fixture plus deterministic waveform controls; not an ASR quality benchmark",
            "confidence_metrics": "segment average log-probability and no-speech probability are implementation outputs, not calibrated end-user probabilities",
            "internal_representation": "not measured in this rep",
        },
        "known_assumptions": [
            "the Foundry-qualified pinned JFK fixture is sufficient for a first continuous-audio instrumentation rep",
            "baseline-relative transcript edit distance is a stability measure rather than ground-truth WER",
            "20 dB deterministic white noise and simple gain/silence controls are reconnaissance perturbations, not a full acoustic robustness suite",
        ],
        "known_failure_modes": [
            "single-speaker/single-utterance fixture cannot establish general ASR robustness",
            "tone/silence controls may still trigger hallucinated text and should be recorded rather than filtered",
            "Faster-Whisper segment probabilities do not expose encoder internals",
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
            "raw_input_hash": sha256_json({"fixture": fixture_meta, "sample_rate": SAMPLE_RATE, "expected_phrases": EXPECTED_PHRASES, "variant_ids": [row["id"] for row in rows]}),
            "raw_output_hash": raw_output_hash,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "baseline_transcript": baseline_text,
        "speech_edit_distances": derived["speech_variant_normalized_word_edit_distances"],
        "control_word_counts": derived["no_speech_control_transcript_word_counts"],
        "baseline_repeat_exact": repeat_exact,
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
