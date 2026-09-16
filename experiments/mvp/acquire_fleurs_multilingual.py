#!/usr/bin/env python3
"""Acquire a tiny, bounded FLEURS multilingual corpus through Dataset Viewer.

This is deliberately an acquisition/identity adapter, not a dataset framework. It
fetches one public FLEURS test row for one language in each of the seven FLEURS
geographic groups, records the observed Hub revision before and after acquisition,
and hashes the exact audio bytes and reference text consumed by the experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DATASET = "google/fleurs"
DATASET_API = f"https://huggingface.co/api/datasets/{DATASET}"
ROWS_API = "https://datasets-server.huggingface.co/rows"
SPLIT = "test"
ROW_OFFSET = 0
USER_AGENT = "SemperSupra-model-spelunker/1"

LANGUAGES = [
    {"config": "en_us", "whisper_code": "en", "group": "western_european_we"},
    {"config": "ru_ru", "whisper_code": "ru", "group": "eastern_european_ee"},
    {"config": "ar_eg", "whisper_code": "ar", "group": "central_asia_middle_north_african_cmn"},
    {"config": "sw_ke", "whisper_code": "sw", "group": "sub_saharan_african_ssa"},
    {"config": "hi_in", "whisper_code": "hi", "group": "south_asian_sa"},
    {"config": "th_th", "whisper_code": "th", "group": "south_east_asian_sea"},
    {"config": "ja_jp", "whisper_code": "ja", "group": "chinese_japanase_korean_cjk"},
]


def request_bytes(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def request_json(url: str, timeout: int = 120) -> dict[str, Any]:
    return json.loads(request_bytes(url, timeout=timeout))


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def normalize_license(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.lower()]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                out.append(item.lower())
            elif isinstance(item, dict):
                for key in ("name", "id", "license"):
                    if isinstance(item.get(key), str):
                        out.append(item[key].lower())
        return out
    return [str(value).lower()]


def validate_dataset_meta(meta: dict[str, Any]) -> dict[str, Any]:
    observed_id = meta.get("id") or meta.get("_id")
    if observed_id != DATASET:
        raise RuntimeError(f"unexpected dataset id: {observed_id!r}")
    sha = str(meta.get("sha") or "")
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha.lower()):
        raise RuntimeError(f"dataset API did not return a full Git revision: {sha!r}")
    if bool(meta.get("private")):
        raise RuntimeError("FLEURS unexpectedly became private")
    if meta.get("gated") not in (False, None, "false"):
        raise RuntimeError(f"FLEURS unexpectedly gated: {meta.get('gated')!r}")
    card = meta.get("cardData") or meta.get("card_data") or {}
    licenses = normalize_license(card.get("license"))
    if not any(x in {"cc-by-4.0", "cc_by_4_0", "cc-by-4"} for x in licenses):
        raise RuntimeError(f"expected CC-BY-4.0 dataset metadata, observed {licenses!r}")
    return {
        "id": DATASET,
        "revision": sha,
        "private": False,
        "gated": meta.get("gated"),
        "license": "cc-by-4.0",
    }


def row_url(config: str) -> str:
    return ROWS_API + "?" + urllib.parse.urlencode({
        "dataset": DATASET,
        "config": config,
        "split": SPLIT,
        "offset": ROW_OFFSET,
        "length": 1,
    })


def transcription_from(row: dict[str, Any]) -> str:
    for key in ("transcription", "raw_transcription"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RuntimeError(f"row lacks a transcription field: {sorted(row)}")


def audio_src_from(row: dict[str, Any]) -> str:
    audio = row.get("audio")
    if isinstance(audio, dict) and isinstance(audio.get("src"), str):
        return audio["src"]
    raise RuntimeError(f"row lacks Dataset Viewer audio.src: {type(audio).__name__}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    args = ap.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)

    before = validate_dataset_meta(request_json(DATASET_API))
    samples: list[dict[str, Any]] = []

    for spec in LANGUAGES:
        payload = request_json(row_url(spec["config"]))
        rows = payload.get("rows") or []
        if len(rows) != 1:
            raise RuntimeError(f"expected exactly one row for {spec['config']}, got {len(rows)}")
        item = rows[0]
        row = item.get("row") or {}
        row_idx = int(item.get("row_idx", ROW_OFFSET))
        transcript = transcription_from(row)
        src = audio_src_from(row)
        audio_bytes = request_bytes(src)
        if len(audio_bytes) < 1000:
            raise RuntimeError(f"implausibly small audio for {spec['config']}: {len(audio_bytes)} bytes")

        dest = args.output_dir / f"{spec['config']}-{SPLIT}-{row_idx}.wav"
        dest.write_bytes(audio_bytes)
        reference_bytes = transcript.encode("utf-8")
        sample_id = row.get("id")
        samples.append({
            **spec,
            "split": SPLIT,
            "row_idx": row_idx,
            "dataset_row_id": sample_id,
            "reference": transcript,
            "reference_sha256_utf8": sha256_bytes(reference_bytes),
            "audio_file": dest.name,
            "audio_size_bytes": len(audio_bytes),
            "audio_sha256": sha256_bytes(audio_bytes),
            "row_locator": {
                "dataset": DATASET,
                "config": spec["config"],
                "split": SPLIT,
                "row_idx": row_idx,
            },
        })

    after = validate_dataset_meta(request_json(DATASET_API))
    if before["revision"] != after["revision"]:
        raise RuntimeError(
            f"FLEURS repository revision changed during acquisition: {before['revision']} -> {after['revision']}"
        )

    group_names = {x["group"] for x in samples}
    if len(group_names) != 7:
        raise RuntimeError(f"expected seven distinct geographic groups, got {sorted(group_names)}")

    manifest = {
        "schema_version": 1,
        "dataset": before,
        "acquisition": {
            "method": "huggingface-dataset-viewer-rows",
            "rows_endpoint": ROWS_API,
            "split": SPLIT,
            "offset": ROW_OFFSET,
            "revision_stable_during_acquisition": True,
            "audio_bytes_persisted_in_git": False,
        },
        "samples": samples,
    }
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset_revision": before["revision"],
        "license": before["license"],
        "sample_count": len(samples),
        "configs": [x["config"] for x in samples],
        "groups": sorted(group_names),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
