"""Minimal public-safe Open Images human-verified image-label adapter."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator

HUMAN_SOURCES = {"verification", "crowdsource-verification", "human"}


@dataclass(frozen=True)
class OpenImagesLabel:
    dataset: str
    image_id: str
    external_label_id: str
    external_label: str
    assertion: str
    annotation_source: str
    human_verified: bool
    ground_truth_scope: str

    def as_record(self) -> dict:
        return asdict(self)


def load_class_descriptions(path: str | Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            if len(row) < 2:
                raise ValueError(f"invalid Open Images class-description row: {row!r}")
            mapping[row[0]] = row[1]
    return mapping


def iter_human_image_labels(
    annotation_path: str | Path,
    class_descriptions: dict[str, str],
    *,
    image_ids: set[str] | None = None,
) -> Iterator[OpenImagesLabel]:
    with Path(annotation_path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"ImageID", "Source", "LabelName", "Confidence"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"expected Open Images columns {sorted(required)}, got {reader.fieldnames}")
        for row in reader:
            image_id = row["ImageID"]
            if image_ids is not None and image_id not in image_ids:
                continue
            source = row["Source"].strip()
            if source not in HUMAN_SOURCES:
                raise ValueError(
                    f"unexpected non-human Open Images Source={source!r} for {image_id}; "
                    f"expected one of {sorted(HUMAN_SOURCES)}"
                )
            label_id = row["LabelName"]
            if label_id not in class_descriptions:
                raise ValueError(f"missing class description for Open Images label {label_id!r}")
            confidence = row["Confidence"].strip()
            if confidence == "1":
                assertion = "present"
            elif confidence == "0":
                assertion = "absent"
            else:
                raise ValueError(
                    f"unexpected human-label Confidence={confidence!r} for {image_id}/{label_id}"
                )
            yield OpenImagesLabel(
                dataset="open-images",
                image_id=image_id,
                external_label_id=label_id,
                external_label=class_descriptions[label_id],
                assertion=assertion,
                annotation_source=source,
                human_verified=True,
                ground_truth_scope="image_level_concept_presence",
            )


def group_qualification_items(labels: Iterable[OpenImagesLabel]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for label in labels:
        item = grouped.setdefault(
            label.image_id,
            {
                "dataset": "open-images",
                "image_id": label.image_id,
                "ground_truth_scope": "image_level_concept_presence",
                "verified_present": [],
                "verified_absent": [],
            },
        )
        target = "verified_present" if label.assertion == "present" else "verified_absent"
        item[target].append(
            {
                "external_label_id": label.external_label_id,
                "external_label": label.external_label,
                "annotation_source": label.annotation_source,
            }
        )
    for item in grouped.values():
        item["verified_present"].sort(key=lambda x: (x["external_label"], x["external_label_id"]))
        item["verified_absent"].sort(key=lambda x: (x["external_label"], x["external_label_id"]))
    return [grouped[key] for key in sorted(grouped)]
