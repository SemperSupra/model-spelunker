"""Minimal visual-concept worker contract and direct execution spine.

This module deliberately avoids policy semantics and model-specific behavior.
It turns backend scores into provenance-bearing concept observations while
preserving uncertainty and the distinction between observation and truth.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol, Sequence
import uuid

ASSERTION_STATES = {"candidate", "supported", "contradicted", "unknown", "abstain"}


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class CandidateSpec:
    worker_framework: str
    framework_version: str
    backend_family: str
    model_id: str
    model_revision: str | None
    concept_pack_digest: str
    action_policy: str = "direct-v0"
    toolset: tuple[str, ...] = ("score_concepts",)
    parameters: dict[str, Any] = field(default_factory=dict)

    @property
    def candidate_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True)
class Evidence:
    kind: str
    source: str
    score: float | None = None
    raw_score: float | None = None
    region_xyxy: tuple[float, float, float, float] | None = None
    frame_interval_s: tuple[float, float] | None = None
    text_span: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    observation_id: str
    concept_id: str | None
    label: str
    assertion: str
    evidence: tuple[Evidence, ...]
    counter_evidence: tuple[Evidence, ...] = ()
    parent_observation_id: str | None = None

    def __post_init__(self) -> None:
        if self.assertion not in ASSERTION_STATES:
            raise ValueError(f"unsupported assertion state: {self.assertion}")
        if self.assertion in {"supported", "candidate", "contradicted"} and not (self.evidence or self.counter_evidence):
            raise ValueError("non-unknown observations require evidence or counter-evidence")


@dataclass(frozen=True)
class BackendScore:
    label: str
    concept_id: str | None
    score: float
    raw_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ConceptScorer(Protocol):
    """Model/backend seam for direct concept scoring."""

    family: str
    model_id: str
    model_revision: str | None

    def score(self, image_path: str | Path, concepts: Sequence[dict[str, Any]]) -> Sequence[BackendScore]: ...


def build_run_manifest(
    *,
    candidate: CandidateSpec,
    input_path: str | Path,
    observations: Sequence[Observation],
    execution_lane: str,
    run_id: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or f"vcw-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": "visual_concept_worker_run.v0.1",
        "run_id": run_id,
        "started_at": started_at or now,
        "finished_at": now,
        "execution_lane": execution_lane,
        "candidate": {**asdict(candidate), "candidate_digest": candidate.candidate_digest},
        "input": {
            "kind": "still_image",
            "sha256": sha256_file(input_path),
            "filename": Path(input_path).name,
        },
        "observations": [
            {
                **asdict(obs),
                "evidence": [asdict(e) for e in obs.evidence],
                "counter_evidence": [asdict(e) for e in obs.counter_evidence],
            }
            for obs in observations
        ],
        "safeguards": {
            "ground_truth": False,
            "semantic_authority": False,
            "human_review_status": "unreviewed",
        },
    }
    digest_payload = {k: v for k, v in payload.items() if k not in {"started_at", "finished_at", "run_id", "run_digest"}}
    digest_payload["input"] = {
        "kind": payload["input"]["kind"],
        "sha256": payload["input"]["sha256"],
    }
    payload["run_digest"] = canonical_digest(digest_payload)
    return payload


def run_direct(
    *,
    scorer: ConceptScorer,
    candidate: CandidateSpec,
    image_path: str | Path,
    concepts: Sequence[dict[str, Any]],
    top_k: int = 10,
    assertion: str = "candidate",
    execution_lane: str = "trusted-local",
) -> dict[str, Any]:
    """Run the smallest non-agentic control: whole image -> backend -> ledger."""
    if assertion not in ASSERTION_STATES:
        raise ValueError(f"unsupported assertion state: {assertion}")
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    if scorer.family != candidate.backend_family:
        raise ValueError("candidate/backend family mismatch")
    if scorer.model_id != candidate.model_id or scorer.model_revision != candidate.model_revision:
        raise ValueError("candidate/model identity mismatch")

    scores = list(scorer.score(image_path, concepts))
    scores.sort(key=lambda item: item.score, reverse=True)
    observations: list[Observation] = []
    for rank, item in enumerate(scores[:top_k], start=1):
        evidence = Evidence(
            kind="visual_model_score",
            source=f"{scorer.family}:{scorer.model_id}",
            score=float(item.score),
            raw_score=None if item.raw_score is None else float(item.raw_score),
            metadata=dict(item.metadata),
        )
        observations.append(
            Observation(
                observation_id=f"obs-{rank:04d}-{canonical_digest({'label': item.label, 'concept_id': item.concept_id})[:8]}",
                concept_id=item.concept_id,
                label=item.label,
                assertion=assertion,
                evidence=(evidence,),
            )
        )

    return build_run_manifest(
        candidate=candidate,
        input_path=image_path,
        observations=observations,
        execution_lane=execution_lane,
    )
