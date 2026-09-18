"""Real-model tools and a bounded observation-dependent policy for Gate 3."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

from PIL import Image

from visual_active_controller import ActionRequest, run_active_skeleton
from visual_concept_worker_core import BackendScore, CandidateSpec, Evidence, Observation


def observations_from_manifest(manifest: dict[str, Any]) -> tuple[Observation, ...]:
    out: list[Observation] = []
    for item in manifest["observations"]:
        evidence = tuple(Evidence(**e) for e in item.get("evidence", []))
        counter = tuple(Evidence(**e) for e in item.get("counter_evidence", []))
        out.append(
            Observation(
                observation_id=item["observation_id"],
                concept_id=item.get("concept_id"),
                label=item["label"],
                assertion=item["assertion"],
                evidence=evidence,
                counter_evidence=counter,
                parent_observation_id=item.get("parent_observation_id"),
            )
        )
    return tuple(out)


class MarginProbePolicy:
    """Take at most one crop when the whole-image top-2 margin is below threshold."""

    def __init__(self, *, threshold: float, bbox_norm: Sequence[float], top_k: int) -> None:
        self.threshold = float(threshold)
        self.bbox_norm = tuple(float(x) for x in bbox_norm)
        self.top_k = int(top_k)
        if len(self.bbox_norm) != 4:
            raise ValueError("bbox_norm must contain four values")
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")

    def choose(self, *, observations, trace, remaining_actions):
        if trace or remaining_actions < 1:
            return None
        whole = []
        for obs in observations:
            for e in obs.evidence:
                if e.kind == "visual_model_score" and e.region_xyxy is None and e.score is not None:
                    whole.append((float(e.score), obs))
                    break
        whole.sort(key=lambda pair: pair[0], reverse=True)
        if len(whole) < 2:
            return None
        margin = whole[0][0] - whole[1][0]
        if margin >= self.threshold:
            return None
        return ActionRequest(
            tool="crop_score",
            parameters={
                "bbox_norm": list(self.bbox_norm),
                "top_k": self.top_k,
                "trigger": {
                    "kind": "top2_margin_below_threshold",
                    "observed_margin": margin,
                    "threshold": self.threshold,
                },
            },
            parent_observation_id=whole[0][1].observation_id,
        )


class CropScoreTool:
    def __init__(self, *, scorer, concepts: Sequence[dict[str, Any]]) -> None:
        self.scorer = scorer
        self.concepts = tuple(concepts)

    def execute(self, *, image_path, request: ActionRequest, action_id: str):
        bbox = request.parameters.get("bbox_norm")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("crop_score requires bbox_norm[4]")
        x1n, y1n, x2n, y2n = (float(v) for v in bbox)
        if not (0.0 <= x1n < x2n <= 1.0 and 0.0 <= y1n < y2n <= 1.0):
            raise ValueError(f"invalid normalized crop bbox: {bbox!r}")
        top_k = int(request.parameters.get("top_k", 3))
        if top_k < 1:
            raise ValueError("crop_score top_k must be >= 1")

        image = Image.open(image_path).convert("RGB")
        xyxy = (
            int(round(x1n * image.width)),
            int(round(y1n * image.height)),
            int(round(x2n * image.width)),
            int(round(y2n * image.height)),
        )
        if xyxy[0] >= xyxy[2] or xyxy[1] >= xyxy[3]:
            raise ValueError(f"crop collapsed after pixel conversion: {xyxy!r}")
        crop = image.crop(xyxy)
        with TemporaryDirectory(prefix="vcw-active-probe-") as tmp:
            path = Path(tmp) / "probe.png"
            crop.save(path)
            scores = sorted(
                self.scorer.score(path, self.concepts),
                key=lambda item: item.score,
                reverse=True,
            )[:top_k]

        out: list[Observation] = []
        for index, item in enumerate(scores, start=1):
            out.append(
                Observation(
                    observation_id=f"tool-local-{index}",
                    concept_id=item.concept_id,
                    label=item.label,
                    assertion="candidate",
                    evidence=(
                        Evidence(
                            kind="visual_model_score",
                            source=f"{self.scorer.family}:{self.scorer.model_id}",
                            score=float(item.score),
                            raw_score=None if item.raw_score is None else float(item.raw_score),
                            region_xyxy=tuple(float(v) for v in xyxy),
                            metadata={
                                **dict(item.metadata),
                                "view": "active_crop",
                                "action_id": action_id,
                            },
                        ),
                    ),
                )
            )
        return out


def run_active_real(*, candidate: CandidateSpec, image_path, initial_manifest, scorer, concepts):
    params = candidate.parameters
    policy_name = str(params.get("policy", ""))
    if policy_name != "uncertainty-margin-one-probe-v0":
        raise ValueError(f"unsupported active policy: {policy_name}")
    policy = MarginProbePolicy(
        threshold=float(params["margin_threshold"]),
        bbox_norm=params["probe_bbox_norm"],
        top_k=int(params.get("top_k_per_probe", 3)),
    )
    return run_active_skeleton(
        candidate=candidate,
        image_path=image_path,
        initial_observations=observations_from_manifest(initial_manifest),
        policy=policy,
        tools={"crop_score": CropScoreTool(scorer=scorer, concepts=concepts)},
        max_actions=int(params["max_actions"]),
        execution_lane="public-ringer",
    )
