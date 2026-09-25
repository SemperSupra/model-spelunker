#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import av
from faster_whisper import WhisperModel


REQUIRED_TOKENS={"blue","lantern","red","bridge","count","seven"}


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


_DIGIT_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}


def words(value: str) -> list[str]:
    return [
        _DIGIT_WORDS.get(token, token)
        for token in re.findall(r"[a-z0-9]+", value.lower())
    ]


def word_error_count(expected: list[str], actual: list[str]) -> int:
    prev=list(range(len(actual)+1))
    for i,left in enumerate(expected,start=1):
        cur=[i]
        for j,right in enumerate(actual,start=1):
            cur.append(min(
                cur[-1]+1,
                prev[j]+1,
                prev[j-1]+(0 if left==right else 1),
            ))
        prev=cur
    return prev[-1]


def audio_duration(path: Path) -> float | None:
    with av.open(str(path)) as container:
        if container.duration is not None:
            return float(container.duration) / float(av.time_base)
        for stream in container.streams.audio:
            if stream.duration is not None and stream.time_base is not None:
                return float(stream.duration * stream.time_base)
    return None


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--model-dir",type=Path,required=True)
    parser.add_argument("--audio",type=Path,required=True)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--generation-evidence",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--max-wer",type=float,default=0.10)
    args=parser.parse_args()

    expected=args.source.read_text(encoding="utf-8").strip()
    generation=json.loads(args.generation_evidence.read_text(encoding="utf-8"))
    audio_bytes=args.audio.read_bytes()
    audio_sha=sha256_bytes(audio_bytes)
    if audio_sha != (generation.get("output") or {}).get("sha256"):
        raise RuntimeError("audio transfer/hash mismatch")

    duration=audio_duration(args.audio)
    model=WhisperModel(
        str(args.model_dir),
        device="cpu",
        compute_type="int8",
        local_files_only=True,
    )
    segments_iter,info=model.transcribe(
        str(args.audio),
        language="en",
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=False,
        word_timestamps=False,
    )
    transcript="".join(str(seg.text) for seg in segments_iter).strip()
    expected_words=words(expected)
    actual_words=words(transcript)
    errors=word_error_count(expected_words,actual_words)
    wer=errors/max(1,len(expected_words))
    actual_set=set(actual_words)
    missing_tokens=sorted(REQUIRED_TOKENS-actual_set)

    checks={
        "generation_status":generation.get("status")=="generated",
        "audio_size":len(audio_bytes)>1000,
        "duration":duration is not None and 0.5 <= duration <= 30.0,
        "language":str(getattr(info,"language",""))=="en",
        "wer":wer <= args.max_wer,
        "required_tokens":not missing_tokens,
    }
    success=all(checks.values())
    evidence={
        "schema_version":1,
        "record_type":"tts-independent-asr-validation",
        "validator":{
            "logical_id":"asr/faster-whisper/tiny",
            "upstream_exact_revision":"d90ca5fe260221311c53c58e660288d3deb8d356",
            "approved_digest":"sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42",
            "faster_whisper_version":"1.2.1",
            "ctranslate2_version":"4.6.0",
        },
        "audio":{
            "sha256":audio_sha,
            "size_bytes":len(audio_bytes),
            "duration_seconds":duration,
        },
        "expected":{
            "sha256":sha256_bytes(expected.encode("utf-8")),
            "word_count":len(expected_words),
        },
        "transcript":{
            "sha256":sha256_bytes(transcript.encode("utf-8")),
            "word_count":len(actual_words),
            "language":str(getattr(info,"language","")),
            "language_probability":float(getattr(info,"language_probability",0.0)),
            "word_errors":errors,
            "word_error_rate":round(wer,6),
            "missing_required_tokens":missing_tokens,
            "text_retained":False,
        },
        "thresholds":{"max_word_error_rate":args.max_wer},
        "checks":checks,
        "success":success,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
    print(json.dumps(evidence,sort_keys=True))
    return 0 if success else 1


if __name__=="__main__":
    raise SystemExit(main())
