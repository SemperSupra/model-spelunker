#!/usr/bin/env python3
"""Descriptive, no-ground-truth analysis and repeatability comparison for visual batches."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
import json
from pathlib import Path
import re
from typing import Any, Iterable

from visual_concept_worker_core import canonical_digest


@dataclass(frozen=True)
class ResultRecord:
    asset_id: str
    input_sha256: str
    result_digest: str
    result: dict[str, Any]


@dataclass(frozen=True)
class Batch:
    candidate_digest: str
    treatment: str
    results: dict[str, ResultRecord]
    failures: tuple[dict[str, Any], ...]

    @property
    def key(self) -> str:
        return f"{self.treatment}:{self.candidate_digest[:12]}"


def _concept_key(item: dict[str, Any]) -> str:
    concept_id = item.get("concept_id")
    if concept_id:
        return str(concept_id)
    label = re.sub(r"\s+", " ", str(item.get("label", "")).strip().lower())
    return f"label:{label}"


def _observations(result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result.get("observations"), list):
        return list(result["observations"])
    worker = result.get("worker_run")
    if isinstance(worker, dict) and isinstance(worker.get("observations"), list):
        return list(worker["observations"])
    raise ValueError("result does not contain visual worker observations")


def _semantic_projection(result: dict[str, Any]) -> list[dict[str, Any]]:
    projected = []
    for obs in _observations(result):
        evidence = []
        for row in obs.get("evidence", []):
            evidence.append(
                {
                    "kind": row.get("kind"),
                    "source": row.get("source"),
                    "score": row.get("score"),
                    "raw_score": row.get("raw_score"),
                    "region_xyxy": row.get("region_xyxy"),
                    "frame_interval_s": row.get("frame_interval_s"),
                    "text_span": row.get("text_span"),
                    "metadata": row.get("metadata", {}),
                }
            )
        counter = []
        for row in obs.get("counter_evidence", []):
            counter.append(
                {
                    "kind": row.get("kind"),
                    "source": row.get("source"),
                    "score": row.get("score"),
                    "raw_score": row.get("raw_score"),
                    "region_xyxy": row.get("region_xyxy"),
                    "frame_interval_s": row.get("frame_interval_s"),
                    "text_span": row.get("text_span"),
                    "metadata": row.get("metadata", {}),
                }
            )
        projected.append(
            {
                "concept_key": _concept_key(obs),
                "concept_id": obs.get("concept_id"),
                "label": obs.get("label"),
                "assertion": obs.get("assertion"),
                "evidence": evidence,
                "counter_evidence": counter,
                "parent_observation_id": obs.get("parent_observation_id"),
            }
        )
    return sorted(projected, key=lambda x: canonical_digest(x))


def _concept_set(result: dict[str, Any]) -> set[str]:
    return {_concept_key(obs) for obs in _observations(result)}


def load_batch(path: str | Path) -> Batch:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate_digest = str(manifest["candidate_digest"])
    treatment = str(manifest["treatment"])
    results: dict[str, ResultRecord] = {}
    for row in manifest.get("results", []):
        asset_id = str(row["asset_id"])
        if asset_id in results:
            raise ValueError(f"duplicate result asset_id: {asset_id}")
        output = manifest_path.parent / str(row["output_file"])
        result = json.loads(output.read_text(encoding="utf-8"))
        observed_sha = (
            result.get("input", {}).get("sha256")
            or result.get("worker_run", {}).get("input", {}).get("sha256")
        )
        expected_sha = str(row["input_sha256"])
        if observed_sha and observed_sha != expected_sha:
            raise ValueError(f"batch/result input SHA mismatch for {asset_id}")
        results[asset_id] = ResultRecord(
            asset_id=asset_id,
            input_sha256=expected_sha,
            result_digest=str(row["result_digest"]),
            result=result,
        )
    return Batch(
        candidate_digest=candidate_digest,
        treatment=treatment,
        results=results,
        failures=tuple(manifest.get("failures", [])),
    )


def analyze_batches(batches: Iterable[Batch]) -> dict[str, Any]:
    batch_list = list(batches)
    if not batch_list:
        raise ValueError("at least one batch is required")
    keys = [b.key for b in batch_list]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate candidate/treatment batch")

    by_key = {b.key: b for b in batch_list}
    all_assets = sorted(
        set().union(*(set(b.results) | {str(f.get("asset_id")) for f in b.failures if f.get("asset_id")} for b in batch_list))
    )

    candidate_summary: dict[str, Any] = {}
    concept_frequency: dict[str, dict[str, int]] = defaultdict(dict)
    asset_rows: list[dict[str, Any]] = []

    for key, batch in sorted(by_key.items()):
        assertions = Counter()
        evidence_kinds = Counter()
        ocr_assets: set[str] = set()
        observation_count = 0
        for asset_id, record in batch.results.items():
            seen_concepts: set[str] = set()
            for obs in _observations(record.result):
                observation_count += 1
                assertions[str(obs.get("assertion", ""))] += 1
                ckey = _concept_key(obs)
                seen_concepts.add(ckey)
                for evidence in obs.get("evidence", []):
                    kind = str(evidence.get("kind", ""))
                    if kind:
                        evidence_kinds[kind] += 1
                        if kind == "ocr_text":
                            ocr_assets.add(asset_id)
            for ckey in seen_concepts:
                concept_frequency[ckey][key] = concept_frequency[ckey].get(key, 0) + 1
        candidate_summary[key] = {
            "treatment": batch.treatment,
            "candidate_digest": batch.candidate_digest,
            "result_assets": len(batch.results),
            "failed_assets": len(batch.failures),
            "observation_count": observation_count,
            "assertion_counts": dict(sorted(assertions.items())),
            "evidence_kind_counts": dict(sorted(evidence_kinds.items())),
            "ocr_associated_assets": sorted(ocr_assets),
        }

    for asset_id in all_assets:
        per_candidate: dict[str, Any] = {}
        observed_sets: list[set[str]] = []
        semantic_groups: dict[str, list[str]] = defaultdict(list)
        for key, batch in sorted(by_key.items()):
            record = batch.results.get(asset_id)
            if record is None:
                per_candidate[key] = {"status": "missing", "concept_count": 0, "concepts": []}
                continue
            concepts = sorted(_concept_set(record.result))
            cset = set(concepts)
            observed_sets.append(cset)
            semantic_groups[canonical_digest(_semantic_projection(record.result))].append(key)
            per_candidate[key] = {
                "status": "observed",
                "concept_count": len(concepts),
                "concepts": concepts,
            }
        union = set().union(*observed_sets) if observed_sets else set()
        intersection = set.intersection(*observed_sets) if observed_sets else set()
        asset_rows.append(
            {
                "asset_id": asset_id,
                "candidates": per_candidate,
                "union_concepts": sorted(union),
                "intersection_all_observed_candidates": sorted(intersection),
                "disagreement_concepts": sorted(union - intersection),
                "semantic_duplicate_groups": sorted(
                    [sorted(v) for v in semantic_groups.values() if len(v) > 1]
                ),
            }
        )

    pairwise: list[dict[str, Any]] = []
    for left_key, right_key in combinations(sorted(by_key), 2):
        left = by_key[left_key]
        right = by_key[right_key]
        shared_assets = sorted(set(left.results) & set(right.results))
        equal_assets = 0
        left_only_total = 0
        right_only_total = 0
        intersection_total = 0
        for asset_id in shared_assets:
            lset = _concept_set(left.results[asset_id].result)
            rset = _concept_set(right.results[asset_id].result)
            if lset == rset:
                equal_assets += 1
            intersection_total += len(lset & rset)
            left_only_total += len(lset - rset)
            right_only_total += len(rset - lset)
        pairwise.append(
            {
                "left": left_key,
                "right": right_key,
                "shared_assets": len(shared_assets),
                "equal_concept_set_assets": equal_assets,
                "different_concept_set_assets": len(shared_assets) - equal_assets,
                "concept_intersection_total": intersection_total,
                "left_only_concepts_total": left_only_total,
                "right_only_concepts_total": right_only_total,
            }
        )

    payload = {
        "schema_version": "visual_no_gold_analysis.v0.1",
        "candidates": candidate_summary,
        "assets": asset_rows,
        "pairwise": pairwise,
        "concept_asset_frequency_by_candidate": {
            concept: dict(sorted(counts.items()))
            for concept, counts in sorted(concept_frequency.items())
        },
        "safeguards": {
            "ground_truth_used": False,
            "accuracy_metrics_present": False,
            "candidate_ranking_present": False,
            "not_observed_means_absent": False,
            "seed_reference_used_for_scoring": False,
        },
    }
    payload["analysis_digest"] = canonical_digest(payload)
    return payload


def compare_batch_sets(left_batches: Iterable[Batch], right_batches: Iterable[Batch]) -> dict[str, Any]:
    left = {b.key: b for b in left_batches}
    right = {b.key: b for b in right_batches}
    if len(left) != len(list(left.values())) or len(right) != len(list(right.values())):
        raise ValueError("duplicate batch key")

    if set(left) != set(right):
        payload = {
            "schema_version": "visual_repeatability_comparison.v0.1",
            "repeatability_class": "configuration_drift",
            "left_only_candidates": sorted(set(left) - set(right)),
            "right_only_candidates": sorted(set(right) - set(left)),
            "candidates": [],
        }
        payload["comparison_digest"] = canonical_digest(payload)
        return payload

    rows: list[dict[str, Any]] = []
    aggregate = Counter()
    for key in sorted(left):
        lb = left[key]
        rb = right[key]
        assets = sorted(set(lb.results) | set(rb.results))
        candidate_counts = Counter()
        asset_rows = []
        for asset_id in assets:
            lrec = lb.results.get(asset_id)
            rrec = rb.results.get(asset_id)
            if lrec is None or rrec is None:
                klass = "missing_result"
            elif lrec.input_sha256 != rrec.input_sha256:
                klass = "input_identity_drift"
            elif lrec.result_digest == rrec.result_digest:
                klass = "stable_identity_equal"
            elif _semantic_projection(lrec.result) == _semantic_projection(rrec.result):
                klass = "identity_drift_semantic_equal"
            else:
                klass = "semantic_drift"
            candidate_counts[klass] += 1
            aggregate[klass] += 1
            asset_rows.append({"asset_id": asset_id, "class": klass})
        rows.append(
            {
                "candidate": key,
                "counts": dict(sorted(candidate_counts.items())),
                "assets": asset_rows,
            }
        )

    if aggregate["semantic_drift"] or aggregate["input_identity_drift"] or aggregate["missing_result"]:
        overall = "semantic_or_input_drift"
    elif aggregate["identity_drift_semantic_equal"]:
        overall = "semantic_stable_identity_drift"
    else:
        overall = "stable_identity"

    payload = {
        "schema_version": "visual_repeatability_comparison.v0.1",
        "repeatability_class": overall,
        "summary": dict(sorted(aggregate.items())),
        "candidates": rows,
        "safeguards": {
            "volatile_file_bytes_used_as_repeatability_oracle": False,
            "semantic_drift_normalized_away": False,
            "candidate_ranking_present": False,
        },
    }
    payload["comparison_digest"] = canonical_digest(payload)
    return payload
