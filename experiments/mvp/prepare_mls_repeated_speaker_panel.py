#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
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
    need = int(manifest["utterances_per_speaker"])
    min_d = float(manifest["selection_rule"]["min_duration_seconds"])
    max_d = float(manifest["selection_rule"]["max_duration_seconds"])
    columns = ["audio", "transcript", "audio_duration", "speaker_id", "chapter_id", "file", "id"]

    resolved = {
        "dataset_repository": manifest["dataset_repository"],
        "dataset_revision": manifest["dataset_revision"],
        "license_spdx": manifest["license_spdx"],
        "split": manifest["split"],
        "utterances_per_speaker": need,
        "selection_rule": manifest["selection_rule"],
        "speaker_freeze_provenance": manifest["speaker_freeze_provenance"],
        "languages": [],
    }

    for lang in manifest["languages"]:
        config = lang["config"]
        target_speakers = [str(x) for x in lang["speaker_ids"]]
        target_set = set(target_speakers)
        selected: dict[str, list[dict]] = defaultdict(list)
        parquet_path = args.parquet_dir / f"{config}.parquet"
        parquet_bytes = parquet_path.read_bytes()
        table = pq.read_table(parquet_path, columns=columns)
        for idx, row in enumerate(table.to_pylist()):
            speaker = str(row["speaker_id"])
            if speaker not in target_set or len(selected[speaker]) >= need:
                continue
            duration = float(row["audio_duration"])
            if not (min_d <= duration <= max_d):
                continue
            audio_obj = row["audio"] or {}
            audio_bytes = audio_obj.get("bytes") if isinstance(audio_obj, dict) else None
            if not audio_bytes:
                continue
            sample_id = str(row["id"])
            file_name = str(row.get("file") or audio_obj.get("path") or f"{sample_id}.audio")
            suffix = Path(file_name).suffix or ".audio"
            utterance_index = len(selected[speaker]) + 1
            local_file = f"{config}-{speaker}-utt{utterance_index}-{sample_id}{suffix}"
            (args.samples_dir / local_file).write_bytes(audio_bytes)
            selected[speaker].append({
                "utterance_index": utterance_index,
                "sample_id": sample_id,
                "speaker_id": speaker,
                "chapter_id": str(row["chapter_id"]),
                "source_row_index": idx,
                "file": file_name,
                "transcript": str(row["transcript"]),
                "audio_duration_seconds": duration,
                "audio_sha256": sha256_bytes(audio_bytes),
                "audio_size_bytes": len(audio_bytes),
                "local_file": local_file,
            })
            if all(len(selected[s]) >= need for s in target_speakers):
                break
        missing = {s: len(selected[s]) for s in target_speakers if len(selected[s]) != need}
        if missing:
            raise RuntimeError(f"{config}: insufficient eligible utterances for frozen speakers: {missing}")
        resolved["languages"].append({
            "config": config,
            "expected_language": lang["expected_language"],
            "source_parquet_path": lang["parquet_path"],
            "source_parquet_sha256": sha256_bytes(parquet_bytes),
            "source_parquet_size_bytes": len(parquet_bytes),
            "speakers": [
                {"speaker_id": s, "utterances": selected[s]}
                for s in target_speakers
            ],
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(resolved, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "languages": len(resolved["languages"]),
        "speakers": sum(len(x["speakers"]) for x in resolved["languages"]),
        "utterances": sum(len(s["utterances"]) for x in resolved["languages"] for s in x["speakers"]),
        "speaker_ids": {x["config"]: [s["speaker_id"] for s in x["speakers"]] for x in resolved["languages"]},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
