#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

DATASET_REPO = "PolyAI/minds14"
DATASET_REVISION = "40ce77cb32a384e4d50a568e1ec39ac804019d33"
DATASET_LICENSE = "CC-BY-4.0"
CONFIGS = {
    "de-DE": "de",
    "en-US": "en",
    "fr-FR": "fr",
}
TARGET_INTENTS = (1, 12)
PARQUET_NAME = "train-00000-of-00001.parquet"


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "SemperSupra-model-spelunker/1"})
    with urllib.request.urlopen(req, timeout=240) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def extract_audio_bytes(row: dict[str, Any]) -> tuple[bytes, str]:
    audio = row.get("audio")
    if not isinstance(audio, dict):
        raise RuntimeError(f"unexpected audio cell type: {type(audio)!r}")
    raw = audio.get("bytes")
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise RuntimeError("parquet audio cell did not contain embedded bytes")
    source_path = str(audio.get("path") or row.get("path") or "sample.wav")
    return bytes(raw), source_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--work-dir", type=Path, default=Path("panel-work"))
    p.add_argument("--output-dir", type=Path, default=Path("panel"))
    p.add_argument("--manifest", type=Path, default=Path("out/minds14-panel.json"))
    args = p.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)

    source_files = []
    samples = []
    for config, expected_language in CONFIGS.items():
        relpath = f"{config}/{PARQUET_NAME}"
        url = f"https://huggingface.co/datasets/{DATASET_REPO}/resolve/{DATASET_REVISION}/{relpath}?download=true"
        parquet_path = args.work_dir / f"{config}.parquet"
        download(url, parquet_path)
        observed_sha = sha256_file(parquet_path)
        source_files.append({
            "config": config,
            "path": relpath,
            "url": url,
            "size_bytes": parquet_path.stat().st_size,
            "sha256": observed_sha,
        })

        table = pq.read_table(parquet_path)
        rows = table.to_pylist()
        if not rows:
            raise RuntimeError(f"empty parquet for {config}")

        for intent in TARGET_INTENTS:
            selected_index = None
            selected_row = None
            for idx, row in enumerate(rows):
                if int(row.get("intent_class")) == intent:
                    selected_index = idx
                    selected_row = row
                    break
            if selected_row is None or selected_index is None:
                raise RuntimeError(f"no intent {intent} row found for {config}")

            audio_bytes, source_audio_path = extract_audio_bytes(selected_row)
            suffix = Path(source_audio_path).suffix or ".wav"
            sample_id = f"{config}-intent-{intent}"
            audio_path = args.output_dir / f"{sample_id}{suffix}"
            audio_path.write_bytes(audio_bytes)
            samples.append({
                "sample_id": sample_id,
                "config": config,
                "expected_language": expected_language,
                "row_index": selected_index,
                "intent_class": intent,
                "source_audio_path": source_audio_path,
                "local_audio_path": str(audio_path),
                "transcription": str(selected_row.get("transcription") or ""),
                "english_transcription": str(selected_row.get("english_transcription") or ""),
                "lang_id": int(selected_row.get("lang_id")),
                "audio_size_bytes": len(audio_bytes),
                "audio_sha256": sha256_bytes(audio_bytes),
            })

    if len(samples) != 6:
        raise RuntimeError(f"expected six panel samples, observed {len(samples)}")
    if len({s["sample_id"] for s in samples}) != 6:
        raise RuntimeError("duplicate sample IDs")

    manifest = {
        "schema_version": 1,
        "dataset": {
            "repository": DATASET_REPO,
            "exact_revision": DATASET_REVISION,
            "license": DATASET_LICENSE,
            "dataset_card": f"https://huggingface.co/datasets/{DATASET_REPO}/tree/{DATASET_REVISION}",
            "selection_policy": "first row for intent_class 1 and 12 in each pinned config parquet",
            "speaker_identity_available": False,
            "speaker_claims_permitted": False,
        },
        "source_files": source_files,
        "samples": samples,
    }
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "manifest": str(args.manifest),
        "samples": len(samples),
        "configs": sorted(CONFIGS),
        "source_bytes": sum(x["size_bytes"] for x in source_files),
        "speaker_identity_available": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
