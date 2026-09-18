#!/usr/bin/env python3
"""Validate the official XM3600 caption feed without downloading image bytes."""
from __future__ import annotations

import json
from pathlib import Path
import urllib.request

from xm3600_adapter import parse_xm3600_record


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=45) as response:
        return response.read().decode("utf-8")


def main() -> int:
    source = json.loads(
        Path("data/external-benchmarks/xm3600-source.json").read_text(encoding="utf-8")
    )
    image_ids = [
        line.strip()
        for line in fetch_text(source["image_ids_url"]).splitlines()
        if line.strip()
    ]
    if len(image_ids) != int(source["expected_images"]):
        raise SystemExit(
            f"XM3600 image-id count drift: expected {source['expected_images']}, got {len(image_ids)}"
        )
    image_id_set = set(image_ids)
    if len(image_id_set) != len(image_ids):
        raise SystemExit("XM3600 image_ids.txt contains duplicates")

    records = []
    with urllib.request.urlopen(source["web_captions_url"], timeout=45) as response:
        for raw in response:
            if not raw.strip():
                continue
            record = json.loads(raw.decode("utf-8"))
            records.append(record)
            if len(records) >= 5:
                break

    if len(records) != 5:
        raise SystemExit(f"expected 5 source records, got {len(records)}")

    normalized = []
    locales = set()
    languages = set()
    for record in records:
        if "imageId" not in record or "imageLocale" not in record or "captions" not in record:
            raise SystemExit(f"official web record shape drift: {sorted(record)}")
        if record["imageId"] not in image_id_set:
            raise SystemExit(f"caption imageId absent from image_ids.txt: {record['imageId']}")
        locales.add(str(record["imageLocale"]))
        captions = parse_xm3600_record(record)
        if not captions:
            raise SystemExit(f"no normalized captions for {record['imageId']}")
        normalized.extend(captions)
        languages.update(item.language for item in captions)

    required = {"en", "de", "th"}
    if not required.issubset(languages):
        raise SystemExit(f"expected multilingual coverage {sorted(required)}, got {sorted(languages)}")
    if len(languages) < 30:
        raise SystemExit(f"unexpectedly narrow language coverage in probe: {len(languages)}")

    result = {
        "schema_version": "xm3600_source_validation.v0.1",
        "status": "pass",
        "image_ids": len(image_ids),
        "records_probed": len(records),
        "captions_normalized": len(normalized),
        "languages_in_probe": sorted(languages),
        "language_count_in_probe": len(languages),
        "image_locales_in_probe": sorted(locales),
        "invariants": {
            "official_source_used": True,
            "official_record_shape_parsed": True,
            "image_id_membership_verified": True,
            "multilingual_coverage_present": True,
            "image_bytes_downloaded": False,
            "private_content_present": False,
        },
    }
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
