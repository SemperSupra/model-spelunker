"""Scope-aware external benchmark scoring for visual-concept workers.

External annotations are authoritative only for their declared benchmark scope.
Mappings other than exact are retained for analysis but excluded from exact
presence scoring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


SCORABLE_MAPPING = "exact"
ALLOWED_MAPPINGS = {"exact", "narrower", "broader", "related", "excluded"}


@dataclass(frozen=True)
class LabelMapping:
    dataset: str
    external_label_id: str
    worker_concept_id: str | None
    mapping: str
    ground_truth_scope: str

    def __post_init__(self) -> None:
        if self.mapping not in ALLOWED_MAPPINGS:
            raise ValueError(f"unsupported mapping relation: {self.mapping}")
        if self.mapping == "exact" and not self.worker_concept_id:
            raise ValueError("exact mappings require worker_concept_id")


def load_mappings(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], LabelMapping]:
    out: dict[tuple[str, str], LabelMapping] = {}
    for row in rows:
        item = LabelMapping(
            dataset=str(row["dataset"]),
            external_label_id=str(row["external_label_id"]),
            worker_concept_id=row.get("worker_concept_id", row.get("cpe_concept_id")),
            mapping=str(row["mapping"]),
            ground_truth_scope=str(row["ground_truth_scope"]),
        )
        key = (item.dataset, item.external_label_id)
        if key in out:
            raise ValueError(f"duplicate external mapping: {key}")
        out[key] = item
    return out


def observation_concepts(observations: Sequence[dict[str, Any]]) -> set[str]:
    """Return concepts asserted as supported, not merely proposed as candidates."""
    out: set[str] = set()
    for obs in observations:
        if obs.get("assertion") != "supported":
            continue
        concept_id = obs.get("concept_id")
        if concept_id:
            out.add(str(concept_id))
    return out


def score_presence_item(
    *,
    item: Mapping[str, Any],
    observations: Sequence[dict[str, Any]],
    mappings: Mapping[tuple[str, str], LabelMapping],
) -> dict[str, Any]:
    dataset = str(item["dataset"])
    scope = str(item["ground_truth_scope"])
    observed = observation_concepts(observations)

    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    decisions: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for assertion, bucket in (
        ("present", item.get("verified_present", [])),
        ("absent", item.get("verified_absent", [])),
    ):
        for label in bucket:
            external_label_id = str(label["external_label_id"])
            mapping = mappings.get((dataset, external_label_id))
            if mapping is None:
                excluded.append(
                    {
                        "external_label_id": external_label_id,
                        "reason": "unmapped",
                        "assertion": assertion,
                    }
                )
                continue
            if mapping.ground_truth_scope != scope:
                raise ValueError(
                    f"mapping scope mismatch for {dataset}/{external_label_id}: "
                    f"{mapping.ground_truth_scope!r} != {scope!r}"
                )
            if mapping.mapping != SCORABLE_MAPPING:
                excluded.append(
                    {
                        "external_label_id": external_label_id,
                        "reason": f"mapping_{mapping.mapping}",
                        "assertion": assertion,
                        "worker_concept_id": mapping.worker_concept_id,
                    }
                )
                continue

            concept = str(mapping.worker_concept_id)
            seen = concept in observed
            if assertion == "present":
                outcome = "tp" if seen else "fn"
            else:
                outcome = "fp" if seen else "tn"
            counts[outcome] += 1
            decisions.append(
                {
                    "external_label_id": external_label_id,
                    "worker_concept_id": concept,
                    "verified_assertion": assertion,
                    "observed_by_worker": seen,
                    "outcome": outcome,
                }
            )

    return {
        "dataset": dataset,
        "image_id": item.get("image_id"),
        "ground_truth_scope": scope,
        "counts": counts,
        "decisions": decisions,
        "excluded": excluded,
        "safeguards": {
            "unannotated_labels_scored_as_absent": False,
            "non_exact_mappings_scored": False,
            "policy_ground_truth_claimed": False,
        },
    }


def aggregate_presence_scores(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    totals = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    excluded = 0
    scopes: set[str] = set()
    for item in items:
        scopes.add(str(item["ground_truth_scope"]))
        for key in totals:
            totals[key] += int(item["counts"][key])
        excluded += len(item.get("excluded", []))

    def ratio(n: int, d: int) -> float | None:
        return None if d == 0 else n / d

    tp, fp, tn, fn = totals["tp"], totals["fp"], totals["tn"], totals["fn"]
    return {
        "counts": totals,
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "specificity": ratio(tn, tn + fp),
        "balanced_accuracy": (
            None
            if (tp + fn == 0 or tn + fp == 0)
            else (tp / (tp + fn) + tn / (tn + fp)) / 2
        ),
        "excluded_annotations": excluded,
        "ground_truth_scopes": sorted(scopes),
        "scope_note": (
            "Metrics apply only to explicitly mapped, human-verified annotations "
            "within the declared external benchmark scope."
        ),
    }


def observation_scores(observations: Sequence[dict[str, Any]]) -> dict[str, float]:
    """Extract one whole-image visual score per concept for ranking evaluation."""
    out: dict[str, float] = {}
    for obs in observations:
        concept_id = obs.get("concept_id")
        if not concept_id:
            continue
        scores = []
        for evidence in obs.get("evidence", []):
            if evidence.get("kind") != "visual_model_score":
                continue
            if evidence.get("region_xyxy") is not None:
                continue
            if evidence.get("score") is not None:
                scores.append(float(evidence["score"]))
        if not scores:
            continue
        key = str(concept_id)
        if key in out:
            raise ValueError(f"duplicate whole-image score for concept {key}")
        out[key] = scores[0]
    return out


def score_verified_ranking(
    *,
    item: Mapping[str, Any],
    observations: Sequence[dict[str, Any]],
    mappings: Mapping[tuple[str, str], LabelMapping],
) -> dict[str, Any]:
    """Score human-verified positives against verified negatives without a threshold."""
    dataset = str(item["dataset"])
    scope = str(item["ground_truth_scope"])
    scores = observation_scores(observations)

    positive: list[tuple[str, str, float]] = []
    negative: list[tuple[str, str, float]] = []
    excluded: list[dict[str, Any]] = []
    for assertion, bucket, target in (
        ("present", item.get("verified_present", []), positive),
        ("absent", item.get("verified_absent", []), negative),
    ):
        for label in bucket:
            external_label_id = str(label["external_label_id"])
            mapping = mappings.get((dataset, external_label_id))
            if mapping is None:
                excluded.append(
                    {
                        "external_label_id": external_label_id,
                        "assertion": assertion,
                        "reason": "unmapped",
                    }
                )
                continue
            if mapping.ground_truth_scope != scope:
                raise ValueError(
                    f"mapping scope mismatch for {dataset}/{external_label_id}: "
                    f"{mapping.ground_truth_scope!r} != {scope!r}"
                )
            if mapping.mapping != SCORABLE_MAPPING:
                excluded.append(
                    {
                        "external_label_id": external_label_id,
                        "assertion": assertion,
                        "reason": f"mapping_{mapping.mapping}",
                        "worker_concept_id": mapping.worker_concept_id,
                    }
                )
                continue
            concept = str(mapping.worker_concept_id)
            if concept not in scores:
                excluded.append(
                    {
                        "external_label_id": external_label_id,
                        "assertion": assertion,
                        "reason": "missing_worker_score",
                        "worker_concept_id": concept,
                    }
                )
                continue
            target.append((external_label_id, concept, scores[concept]))

    wins = 0
    ties = 0
    losses = 0
    for _, _, pscore in positive:
        for _, _, nscore in negative:
            if pscore > nscore:
                wins += 1
            elif pscore < nscore:
                losses += 1
            else:
                ties += 1
    pairs = wins + ties + losses

    ranked = sorted(
        [(external, concept, score, "present") for external, concept, score in positive]
        + [(external, concept, score, "absent") for external, concept, score in negative],
        key=lambda row: (-row[2], row[1]),
    )
    k = len(positive)
    positives_in_top_k = sum(row[3] == "present" for row in ranked[:k]) if k else 0
    positive_ranks = [
        rank
        for rank, row in enumerate(ranked, start=1)
        if row[3] == "present"
    ]

    return {
        "dataset": dataset,
        "image_id": item.get("image_id"),
        "ground_truth_scope": scope,
        "verified_positive_count": len(positive),
        "verified_negative_count": len(negative),
        "pairwise": {
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "pairs": pairs,
            "accuracy": None if pairs == 0 else (wins + 0.5 * ties) / pairs,
        },
        "positive_at_k": {
            "k": k,
            "positives_in_top_k": positives_in_top_k,
            "rate": None if k == 0 else positives_in_top_k / k,
        },
        "mean_positive_rank": (
            None if not positive_ranks else sum(positive_ranks) / len(positive_ranks)
        ),
        "ranked_labels": [
            {
                "external_label_id": external,
                "worker_concept_id": concept,
                "score": score,
                "verified_assertion": assertion,
                "rank": rank,
            }
            for rank, (external, concept, score, assertion) in enumerate(ranked, start=1)
        ],
        "excluded": excluded,
        "safeguards": {
            "classification_threshold_invented": False,
            "candidate_state_treated_as_supported": False,
            "unannotated_labels_scored_as_absent": False,
            "policy_ground_truth_claimed": False,
        },
    }


def aggregate_verified_rankings(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    wins = ties = losses = positives = topk_hits = 0
    rank_sum = 0.0
    rank_count = 0
    excluded = 0
    for item in items:
        pair = item["pairwise"]
        wins += int(pair["wins"])
        ties += int(pair["ties"])
        losses += int(pair["losses"])
        positives += int(item["positive_at_k"]["k"])
        topk_hits += int(item["positive_at_k"]["positives_in_top_k"])
        if item["mean_positive_rank"] is not None:
            count = int(item["verified_positive_count"])
            rank_sum += float(item["mean_positive_rank"]) * count
            rank_count += count
        excluded += len(item.get("excluded", []))
    pairs = wins + ties + losses
    return {
        "pairwise": {
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "pairs": pairs,
            "accuracy": None if pairs == 0 else (wins + 0.5 * ties) / pairs,
        },
        "positive_at_k_rate": None if positives == 0 else topk_hits / positives,
        "mean_positive_rank": None if rank_count == 0 else rank_sum / rank_count,
        "excluded_annotations": excluded,
        "scope_note": (
            "Ranking metrics compare only explicitly mapped human-verified positives "
            "against explicitly mapped human-verified negatives. No classification "
            "threshold or policy judgment is implied."
        ),
    }
