"""Deterministic fixed-crop treatment for the public Gate-2 ringer.

This module intentionally contains no planner, detector, OCR, or fusion. It
changes one thing relative to direct-v0: the fixed acquisition policy adds four
quadrant views while preserving the whole-image observation path.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

from PIL import Image

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


def _observation_id(*, observation_index: int, label: str, concept_id: str | None, region: Region | None) -> str:
    identity = {
        "observation_index": observation_index,
        "label": label,
        "concept_id": concept_id,
        "region": None if region is None else region.bbox_xyxy,
        "evidence_kind": "visual_model_score",
    }
    return f"obs-{observation_index:04d}-{canonical_digest(identity)[:8]}"


def run_deterministic(
    *,
    scorer: ConceptScorer,
    candidate: CandidateSpec,
    image_path: str | Path,
    concepts: Sequence[dict[str, Any]],
    execution_lane: str = "public-ringer",
) -> dict[str, Any]:
    if candidate.action_policy != "deterministic-v0":
        raise ValueError("candidate action_policy must be deterministic-v0")
    if scorer.family != candidate.backend_family:
        raise ValueError("candidate/backend family mismatch")
    if scorer.model_id != candidate.model_id or scorer.model_revision != candidate.model_revision:
        raise ValueError("candidate/model identity mismatch")

    crop_strategy = str(candidate.parameters.get("crop_strategy", "quadrants-v0"))
    top_k = int(candidate.parameters.get("top_k_per_view", 3))
    if top_k < 1:
        raise ValueError("top_k_per_view must be >= 1")
    if crop_strategy not in {"none", "quadrants-v0"}:
        raise ValueError(f"unsupported deterministic crop strategy: {crop_strategy}")

    required_tools = {"score_concepts"}
    if crop_strategy != "none":
        required_tools.add("crop")
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

    with TemporaryDirectory(prefix="vcw-gate2-") as tmp:
        tmpdir = Path(tmp)
        whole_path = tmpdir / "whole.png"
        image.save(whole_path)
        record_scores(whole_path, None)
        for region in regions:
            crop = image.crop(region.bbox_xyxy)
            crop_path = tmpdir / f"{region.region_id}.png"
            crop.save(crop_path)
            record_scores(crop_path, region)

    return build_run_manifest(
        candidate=candidate,
        input_path=image_path,
        observations=observations,
        execution_lane=execution_lane,
    )
