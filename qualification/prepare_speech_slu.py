#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from faster_whisper import WhisperModel


LOGICAL_ID = "asr/faster-whisper/tiny"
UPSTREAM_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
APPROVED_DIGEST = "sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42"
EXPECTED_PHRASES = ("my fellow americans", "ask not what your country can do for you", "what you can do for your country")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def normalize(value: str) -> str:
    return " ".join(
        "".join(ch.lower() if ch.isalnum() else " " for ch in value).split()
    )


def transcribe(model_dir: Path, fixture: Path) -> dict[str, object]:
    model = WhisperModel(
        str(model_dir),
        device="cpu",
        compute_type="int8",
        local_files_only=True,
    )
    segments_iter, info = model.transcribe(
        str(fixture),
        language="en",
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=False,
        word_timestamps=False,
    )
    segments = []
    for segment in segments_iter:
        segments.append(
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": str(segment.text),
            }
        )
    transcript = "".join(str(row["text"]) for row in segments).strip()
    return {
        "transcript": transcript,
        "segments": segments,
        "language": str(getattr(info, "language", "")),
        "language_probability": float(getattr(info, "language_probability", 0.0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--fixture-meta", type=Path, required=True)
    parser.add_argument("--transcript-output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()

    fixture_meta = json.loads(args.fixture_meta.read_text(encoding="utf-8"))
    fixture_bytes = args.fixture.read_bytes()
    fixture_sha = sha256_bytes(fixture_bytes)
    if fixture_meta.get("sha256") != fixture_sha:
        raise RuntimeError("fixture metadata/hash mismatch")

    result = transcribe(args.model_dir, args.fixture)
    transcript = str(result["transcript"]).strip()
    normalized = normalize(transcript)
    phrase_presence = {phrase: phrase in normalized for phrase in EXPECTED_PHRASES}
    if result["language"] != "en":
        raise RuntimeError(f"unexpected ASR language: {result['language']!r}")
    if not all(phrase_presence.values()):
        raise RuntimeError(
            "ASR transcript failed predeclared phrase gate: "
            + json.dumps(phrase_presence, sort_keys=True)
        )

    transcript_sha = sha256_bytes(transcript.encode("utf-8"))
    evidence = {
        "schema_version": 1,
        "stage": "speech-asr-preparation",
        "model": {
            "logical_id": LOGICAL_ID,
            "upstream_exact_revision": UPSTREAM_REVISION,
            "approved_digest": APPROVED_DIGEST,
        },
        "fixture": fixture_meta,
        "transcript": {
            "sha256": transcript_sha,
            "chars": len(transcript),
            "language": result["language"],
            "language_probability": result["language_probability"],
            "expected_phrase_presence": phrase_presence,
            "segment_count": len(result["segments"]),
        },
    }

    args.transcript_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.transcript_output.write_text(transcript + "\n", encoding="utf-8")
    args.evidence_output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "transcript_sha256": transcript_sha,
                "chars": len(transcript),
                "language": result["language"],
                "phrase_gate": phrase_presence,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
