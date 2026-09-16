#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--parquet-dir", type=Path, required=True)
    p.add_argument("--samples-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.samples_dir.mkdir(parents=True, exist_ok=True)
    resolved = {
        "dataset_repository": manifest["dataset_repository"],
        "dataset_revision": manifest["dataset_revision"],
        "license_spdx": manifest["license_spdx"],
        "split": manifest["split"],
        "selection_rule": manifest["selection_rule"],
        "speakers_per_language": manifest["speakers_per_language"],
        "languages": [],
    }

    min_d = float(manifest["selection_rule"]["min_duration_seconds"])
    max_d = float(manifest["selection_rule"]["max_duration_seconds"])
    need = int(manifest["speakers_per_language"])
    columns = ["audio", "transcript", "audio_duration", "speaker_id", "chapter_id", "file", "id"]

    for lang in manifest["languages"]:
        config = lang["config"]
        parquet_path = args.parquet_dir / f"{config}.parquet"
        parquet_bytes = parquet_path.read_bytes()
        table = pq.read_table(parquet_path, columns=columns)
        chosen = []
        speakers = set()
        for idx, row in enumerate(table.to_pylist()):
            speaker = str(row["speaker_id"])
            if speaker in speakers:
                continue
            duration = float(row["audio_duration"])
            if not (min_d <= duration <= max_d):
                continue
            audio_obj = row["audio"] or {}
            audio_bytes = audio_obj.get("bytes") if isinstance(audio_obj, dict) else None
            if not audio_bytes:
                continue
            file_name = str(row.get("file") or audio_obj.get("path") or f"{row['id']}.audio")
            suffix = Path(file_name).suffix or ".audio"
            sample_id = str(row["id"])
            output_name = f"{config}-{len(chosen)+1}-{sample_id}{suffix}"
            out_path = args.samples_dir / output_name
            out_path.write_bytes(audio_bytes)
            chosen.append({
                "panel_id": f"{config}-speaker-{len(chosen)+1}",
                "config": config,
                "expected_language": lang["expected_language"],
                "source_row_index": idx,
                "sample_id": sample_id,
                "speaker_id": speaker,
                "chapter_id": str(row["chapter_id"]),
                "file": file_name,
                "transcript": str(row["transcript"]),
                "audio_duration_seconds": duration,
                "audio_sha256": sha256_bytes(audio_bytes),
                "audio_size_bytes": len(audio_bytes),
                "local_file": output_name,
            })
            speakers.add(speaker)
            if len(chosen) == need:
                break
        if len(chosen) != need:
            raise RuntimeError(f"{config}: selected {len(chosen)} distinct speakers; expected {need}")
        resolved["languages"].append({
            "config": config,
            "expected_language": lang["expected_language"],
            "source_parquet_path": lang["parquet_path"],
            "source_parquet_sha256": sha256_bytes(parquet_bytes),
            "source_parquet_size_bytes": len(parquet_bytes),
            "selected": chosen,
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(resolved, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "languages": len(resolved["languages"]),
        "selected_speakers": sum(len(x["selected"]) for x in resolved["languages"]),
        "speaker_ids": {x["config"]: [s["speaker_id"] for s in x["selected"]] for x in resolved["languages"]},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
