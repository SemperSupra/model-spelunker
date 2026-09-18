"""Deterministic fixed-crop treatment for the public Gate-2 ringer.

This module intentionally contains no planner, detector, or fusion. It supports
a fixed crop policy plus an optional deterministic OCR adapter so each treatment
dimension can be enabled explicitly and recorded in candidate identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol, Sequence

from PIL import Image, ImageEnhance, ImageOps

from visual_concept_worker_core import (
    CandidateSpec,
    ConceptScorer,
    Evidence,
    Observation,
    build_run_manifest,
    canonical_digest,
)


@dataclass(frozen=True)
class Region:
    region_id: str
    bbox_xyxy: tuple[int, int, int, int]


class TextRecognizer(Protocol):
    source: str

    def recognize(self, image: Image.Image) -> str: ...


class TesseractTextRecognizer:
    """Thin deterministic Tesseract adapter for the OCR treatment."""

    def __init__(self, *, languages: str = "eng+deu", psm: int = 6) -> None:
        self.languages = languages
        self.psm = int(psm)
        self.source = f"tesseract:{languages}:psm-{psm}"

    @staticmethod
    def preprocess(image: Image.Image) -> Image.Image:
        gray = ImageOps.grayscale(image)
        gray = ImageOps.autocontrast(gray)
        gray = ImageEnhance.Sharpness(gray).enhance(1.8)
        gray = gray.resize((gray.width * 2, gray.height * 2))
        return gray.point(lambda p: 255 if p > 160 else 0)

    def recognize(self, image: Image.Image) -> str:
        import pytesseract

        processed = self.preprocess(image)
        text = pytesseract.image_to_string(
            processed,
            lang=self.languages,
            config=f"--psm {self.psm}",
        )
        return " ".join(text.split())


def fixed_regions(image: Image.Image, strategy: str) -> tuple[Region, ...]:
    if strategy == "none":
        return ()
    if strategy != "quadrants-v0":
        raise ValueError(f"unsupported deterministic crop strategy: {strategy}")
    mid_x = image.width // 2
    mid_y = image.height // 2
    if mid_x < 1 or mid_y < 1:
        return ()
    return (
        Region("q1", (0, 0, mid_x, mid_y)),
        Region("q2", (mid_x, 0, image.width, mid_y)),
        Region("q3", (0, mid_y, mid_x, image.height)),
        Region("q4", (mid_x, mid_y, image.width, image.height)),
    )


def _observation_id(
    *,
    observation_index: int,
    label: str,
    concept_id: str | None,
    region: Region | None,
    evidence_kind: str,
) -> str:
    identity = {
        "observation_index": observation_index,
        "label": label,
        "concept_id": concept_id,
        "region": None if region is None else region.bbox_xyxy,
        "evidence_kind": evidence_kind,
    }
    return f"obs-{observation_index:04d}-{canonical_digest(identity)[:8]}"


def run_deterministic(
    *,
    scorer: ConceptScorer,
    candidate: CandidateSpec,
    image_path: str | Path,
    concepts: Sequence[dict[str, Any]],
    text_recognizer: TextRecognizer | None = None,
    execution_lane: str = "public-ringer",
) -> dict[str, Any]:
    if candidate.action_policy != "deterministic-v0":
        raise ValueError("candidate action_policy must be deterministic-v0")
    if scorer.family != candidate.backend_family:
        raise ValueError("candidate/backend family mismatch")
    if scorer.model_id != candidate.model_id or scorer.model_revision != candidate.model_revision:
        raise ValueError("candidate/model identity mismatch")

    crop_strategy = str(candidate.parameters.get("crop_strategy", "quadrants-v0"))
    ocr_strategy = str(candidate.parameters.get("ocr_strategy", "off"))
    top_k = int(candidate.parameters.get("top_k_per_view", 3))
    if top_k < 1:
        raise ValueError("top_k_per_view must be >= 1")
    if crop_strategy not in {"none", "quadrants-v0"}:
        raise ValueError(f"unsupported deterministic crop strategy: {crop_strategy}")
    if ocr_strategy not in {"off", "whole-v0", "whole-and-tiles-v0"}:
        raise ValueError(f"unsupported deterministic OCR strategy: {ocr_strategy}")

    required_tools = {"score_concepts"}
    if crop_strategy != "none":
        required_tools.add("crop")
    if ocr_strategy != "off":
        required_tools.add("ocr")
        if text_recognizer is None:
            raise ValueError("OCR strategy is enabled but no text_recognizer was supplied")
    missing = sorted(required_tools.difference(candidate.toolset))
    if missing:
        raise ValueError(f"candidate toolset is missing required tools: {missing}")

    image = Image.open(image_path).convert("RGB")
    regions = fixed_regions(image, crop_strategy)
    observations: list[Observation] = []
    observation_index = 0

    def record_scores(view_path: Path, region: Region | None) -> None:
        nonlocal observation_index
        scores = sorted(
            scorer.score(view_path, concepts),
            key=lambda item: item.score,
            reverse=True,
        )[:top_k]
        for item in scores:
            observation_index += 1
            observations.append(
                Observation(
                    observation_id=_observation_id(
                        observation_index=observation_index,
                        label=item.label,
                        concept_id=item.concept_id,
                        region=region,
                        evidence_kind="visual_model_score",
                    ),
                    concept_id=item.concept_id,
                    label=item.label,
                    assertion="candidate",
                    evidence=(
                        Evidence(
                            kind="visual_model_score",
                            source=f"{scorer.family}:{scorer.model_id}",
                            score=float(item.score),
                            raw_score=None if item.raw_score is None else float(item.raw_score),
                            region_xyxy=None if region is None else tuple(float(v) for v in region.bbox_xyxy),
                            metadata={
                                **dict(item.metadata),
                                "view": "whole" if region is None else region.region_id,
                            },
                        ),
                    ),
                )
            )

    def record_ocr(view: Image.Image, region: Region | None) -> None:
        nonlocal observation_index
        if text_recognizer is None:
            return
        text = text_recognizer.recognize(view)
        if not text:
            return
        observation_index += 1
        observations.append(
            Observation(
                observation_id=_observation_id(
                    observation_index=observation_index,
                    label="visible text",
                    concept_id="content.contains.visible_text",
                    region=region,
                    evidence_kind="ocr_text",
                ),
                concept_id="content.contains.visible_text",
                label="visible text",
                assertion="candidate",
                evidence=(
                    Evidence(
                        kind="ocr_text",
                        source=text_recognizer.source,
                        region_xyxy=None
                        if region is None
                        else tuple(float(v) for v in region.bbox_xyxy),
                        text_span=text,
                        metadata={"view": "whole" if region is None else region.region_id},
                    ),
                ),
            )
        )

    with TemporaryDirectory(prefix="vcw-gate2-") as tmp:
        tmpdir = Path(tmp)
        whole_path = tmpdir / "whole.png"
        image.save(whole_path)
        record_scores(whole_path, None)
        if ocr_strategy in {"whole-v0", "whole-and-tiles-v0"}:
            record_ocr(image, None)
        for region in regions:
            crop = image.crop(region.bbox_xyxy)
            crop_path = tmpdir / f"{region.region_id}.png"
            crop.save(crop_path)
            record_scores(crop_path, region)
            if ocr_strategy == "whole-and-tiles-v0":
                record_ocr(crop, region)

    return build_run_manifest(
        candidate=candidate,
        input_path=image_path,
        observations=observations,
        execution_lane=execution_lane,
    )
