"""Crossmodal-3600 caption adapter and deterministic ranking-trial builder."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


@dataclass(frozen=True)
class XM3600Caption:
    image_id: str
    language: str
    caption: str
    dataset: str = "xm3600"
    human_generated: bool = True
    ground_truth_scope: str = "human_caption_image_alignment"


def _emit_caption(image_id: Any, language: Any, caption: Any) -> XM3600Caption:
    image_id = str(image_id).strip()
    language = str(language).strip()
    caption = str(caption).strip()
    if not image_id or not language or not caption:
        raise ValueError("XM3600 caption requires non-empty image_id, language, caption")
    return XM3600Caption(image_id=image_id, language=language, caption=caption)


def parse_xm3600_record(record: Mapping[str, Any]) -> list[XM3600Caption]:
    """Accept the common normalized shapes used around XM3600.

    The adapter fails closed on unknown shapes so source-format changes do not
    silently corrupt multilingual qualification data.
    """
    image_id = record.get("image_id") or record.get("imageId") or record.get("id")
    if image_id is None:
        raise ValueError("XM3600 record missing image_id")

    if isinstance(record.get("captions"), dict):
        out: list[XM3600Caption] = []
        for language, captions in record["captions"].items():
            values = captions if isinstance(captions, list) else [captions]
            out.extend(_emit_caption(image_id, language, caption) for caption in values)
        return out

    # Official web_captions.jsonl uses imageId/imageLocale and a list of
    # [language, [caption, ...]] pairs for captions.
    if isinstance(record.get("captions"), list) and record["captions"]:
        if all(
            isinstance(pair, list)
            and len(pair) == 2
            and isinstance(pair[1], list)
            for pair in record["captions"]
        ):
            out: list[XM3600Caption] = []
            for language, captions in record["captions"]:
                out.extend(_emit_caption(image_id, language, caption) for caption in captions)
            return out

    language = record.get("language") or record.get("lang") or record.get("language_id")
    if language is not None and isinstance(record.get("captions"), list):
        return [_emit_caption(image_id, language, caption) for caption in record["captions"]]
    if language is not None and record.get("caption") is not None:
        return [_emit_caption(image_id, language, record["caption"])]

    raise ValueError(f"unsupported XM3600 record shape for image {image_id!r}")


def iter_xm3600_jsonl(path: str | Path) -> Iterator[XM3600Caption]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                yield from parse_xm3600_record(record)
            except Exception as exc:
                raise ValueError(f"invalid XM3600 record at line {line_number}: {exc}") from exc


def group_captions(captions: Iterable[XM3600Caption]) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for item in captions:
        out[item.image_id][item.language].append(item.caption)
    return {
        image_id: {
            language: sorted(dict.fromkeys(values))
            for language, values in sorted(by_language.items())
        }
        for image_id, by_language in sorted(out.items())
    }


def build_caption_ranking_trials(
    captions: Iterable[XM3600Caption],
    *,
    languages: Sequence[str] | None = None,
    decoys_per_trial: int = 3,
) -> list[dict[str, Any]]:
    if decoys_per_trial < 1:
        raise ValueError("decoys_per_trial must be >= 1")
    grouped = group_captions(captions)
    wanted = None if languages is None else set(languages)
    image_ids = sorted(grouped)
    trials: list[dict[str, Any]] = []

    for image_index, image_id in enumerate(image_ids):
        by_language = grouped[image_id]
        for language, references in sorted(by_language.items()):
            if wanted is not None and language not in wanted:
                continue
            decoys: list[dict[str, str]] = []
            offset = 1
            while len(decoys) < decoys_per_trial and offset < len(image_ids) + 1:
                other_id = image_ids[(image_index + offset) % len(image_ids)]
                offset += 1
                if other_id == image_id:
                    continue
                other_caps = grouped.get(other_id, {}).get(language, [])
                if not other_caps:
                    continue
                decoys.append({"image_id": other_id, "caption": other_caps[0]})
            if len(decoys) < decoys_per_trial:
                continue
            trials.append(
                {
                    "dataset": "xm3600",
                    "image_id": image_id,
                    "language": language,
                    "ground_truth_scope": "human_caption_image_alignment",
                    "human_reference_captions": references,
                    "decoy_captions": decoys,
                    "trial_semantics": (
                        "At least one human reference belongs to this image; decoys "
                        "are human captions from different XM3600 images in the same language."
                    ),
                }
            )
    return trials
