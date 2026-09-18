"""Review-queue builder for visual-concept qualification evidence.

This module compares automated observations with each other and with seed
references without treating seed or automated observations as ground truth.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable

from visual_concept_worker_core import canonical_digest


@dataclass(frozen=True)
class BatchEvidence:
    candidate_digest: str
    treatment: str
    results: dict[str, dict[str, Any]]
    failures: tuple[dict[str, Any], ...]

    @property
    def candidate_key(self) -> str:
        return f"{self.treatment}:{self.candidate_digest[:12]}"


def _concept_key(item: dict[str, Any]) -> str:
    concept_id = item.get("concept_id")
    if concept_id:
        return str(concept_id)
    label = str(item.get("label", "")).strip().lower()
    label = re.sub(r"\s+", " ", label)
    return f"label:{label}"


def _observations(result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result.get("observations"), list):
        return list(result["observations"])
    worker_run = result.get("worker_run")
    if isinstance(worker_run, dict) and isinstance(worker_run.get("observations"), list):
        return list(worker_run["observations"])
    raise ValueError("result does not contain visual worker observations")


def load_batch_manifest(path: str | Path) -> BatchEvidence:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate_digest = str(manifest["candidate_digest"])
    treatment = str(manifest["treatment"])
    results: dict[str, dict[str, Any]] = {}
    for item in manifest.get("results", []):
        asset_id = str(item["asset_id"])
        output_file = manifest_path.parent / str(item["output_file"])
        if asset_id in results:
            raise ValueError(f"duplicate batch result asset_id: {asset_id}")
        result = json.loads(output_file.read_text(encoding="utf-8"))
        input_sha = (
            result.get("input", {}).get("sha256")
            or result.get("worker_run", {}).get("input", {}).get("sha256")
        )
        if input_sha and input_sha != item.get("input_sha256"):
            raise ValueError(f"batch/result input SHA mismatch for {asset_id}")
        results[asset_id] = result
    return BatchEvidence(
        candidate_digest=candidate_digest,
        treatment=treatment,
        results=results,
        failures=tuple(manifest.get("failures", [])),
    )


def _seed_assets(benchmark: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entry in benchmark.get("assets", []):
        meta = entry.get("asset", entry)
        asset_id = meta.get("benchmark_asset_id") or entry.get("benchmark_asset_id")
        if not asset_id:
            raise ValueError("benchmark asset missing benchmark_asset_id")
        if asset_id in out:
            raise ValueError(f"duplicate benchmark asset id: {asset_id}")
        out[str(asset_id)] = entry
    return out


def _seed_concepts(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in entry.get("concept_observations", []):
        key = str(item.get("concept_id") or "")
        if not key:
            continue
        out[key] = {
            "concept_id": key,
            "assertion_state": item.get("assertion_state"),
            "status": item.get("status"),
        }
    return out


def _auto_concepts(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for obs in _observations(result):
        key = _concept_key(obs)
        item = grouped.setdefault(
            key,
            {
                "concept_key": key,
                "concept_id": obs.get("concept_id"),
                "labels": set(),
                "assertions": set(),
                "evidence_kinds": set(),
                "observation_count": 0,
            },
        )
        item["labels"].add(str(obs.get("label", "")))
        item["assertions"].add(str(obs.get("assertion", "")))
        item["observation_count"] += 1
        for evidence in obs.get("evidence", []):
            kind = evidence.get("kind")
            if kind:
                item["evidence_kinds"].add(str(kind))
    for item in grouped.values():
        item["labels"] = sorted(item["labels"])
        item["assertions"] = sorted(item["assertions"])
        item["evidence_kinds"] = sorted(item["evidence_kinds"])
    return grouped


def build_review_queue(
    *,
    benchmark: dict[str, Any],
    batches: Iterable[BatchEvidence],
) -> dict[str, Any]:
    seed_assets = _seed_assets(benchmark)
    batch_list = list(batches)
    if not batch_list:
        raise ValueError("at least one automated batch is required")

    candidate_keys = [batch.candidate_key for batch in batch_list]
    if len(candidate_keys) != len(set(candidate_keys)):
        raise ValueError("duplicate candidate/treatment batch supplied")

    items: list[dict[str, Any]] = []
    for asset_id, entry in seed_assets.items():
        seed = _seed_concepts(entry)
        by_candidate: dict[str, dict[str, dict[str, Any]]] = {}
        missing_candidates: list[str] = []
        failure_records: list[dict[str, Any]] = []

        for batch in batch_list:
            result = batch.results.get(asset_id)
            if result is None:
                missing_candidates.append(batch.candidate_key)
                for failure in batch.failures:
                    if str(failure.get("asset_id")) == asset_id:
                        failure_records.append(
                            {
                                "candidate": batch.candidate_key,
                                **failure,
                            }
                        )
                continue
            by_candidate[batch.candidate_key] = _auto_concepts(result)

        union_keys: set[str] = set()
        presence: dict[str, list[str]] = defaultdict(list)
        concept_details: dict[str, dict[str, Any]] = {}
        for candidate_key, concepts in by_candidate.items():
            for key, detail in concepts.items():
                union_keys.add(key)
                presence[key].append(candidate_key)
                concept_details.setdefault(key, detail)

        observed_candidate_count = len(by_candidate)
        disagreements = []
        if observed_candidate_count >= 2:
            for key in sorted(union_keys):
                seen = sorted(presence[key])
                if len(seen) != observed_candidate_count:
                    disagreements.append(
                        {
                            "concept_key": key,
                            "observed_by": seen,
                            "not_observed_by": sorted(set(by_candidate) - set(seen)),
                        }
                    )

        seed_keys = set(seed)
        auto_concept_ids = {
            detail.get("concept_id")
            for detail in concept_details.values()
            if detail.get("concept_id")
        }
        novel = sorted(key for key in auto_concept_ids if key not in seed_keys)
        seed_unobserved = sorted(key for key in seed_keys if key not in auto_concept_ids)

        ocr_present = any(
            "ocr_text" in detail.get("evidence_kinds", [])
            for detail in concept_details.values()
        )
        policy_probes = list(entry.get("policy_probes", []))

        reasons: list[str] = []
        if failure_records or missing_candidates:
            reasons.append("incomplete_automated_evidence")
        if disagreements:
            reasons.append("cross_candidate_disagreement")
        if novel:
            reasons.append("auto_novel_vs_seed_reference")
        if seed_unobserved:
            reasons.append("seed_reference_not_observed_by_auto")
        if ocr_present:
            reasons.append("ocr_evidence_present")
        if policy_probes:
            reasons.append("policy_probe_asset")

        priority_key = (
            0 if failure_records or missing_candidates else 1,
            0 if disagreements else 1,
            0 if novel else 1,
            0 if policy_probes else 1,
            asset_id,
        )

        items.append(
            {
                "asset_id": asset_id,
                "source_filename": entry.get("asset", entry).get("source_filename")
                or entry.get("asset", entry).get("filename"),
                "sha256": entry.get("asset", entry).get("sha256"),
                "policy_probes": policy_probes,
                "seed_reference": {
                    "authority": "seed_not_ground_truth",
                    "concepts": [seed[key] for key in sorted(seed)],
                },
                "automated": {
                    "candidates": {
                        candidate: {
                            "concepts": [
                                concepts[key] for key in sorted(concepts)
                            ]
                        }
                        for candidate, concepts in sorted(by_candidate.items())
                    },
                    "missing_candidates": sorted(missing_candidates),
                    "failures": failure_records,
                },
                "comparison": {
                    "cross_candidate_disagreements": disagreements,
                    "auto_novel_vs_seed_reference": novel,
                    "seed_reference_not_observed_by_auto": seed_unobserved,
                    "note": (
                        "Not observed is not evidence of absence. Seed-reference "
                        "differences are review cues, not accuracy judgments."
                    ),
                },
                "review_reasons": reasons,
                "_priority_key": priority_key,
            }
        )

    items.sort(key=lambda item: item["_priority_key"])
    for index, item in enumerate(items, start=1):
        item.pop("_priority_key", None)
        item["review_order"] = index

    summary = {
        "assets": len(items),
        "candidates": candidate_keys,
        "assets_with_incomplete_evidence": sum(
            bool(item["automated"]["missing_candidates"] or item["automated"]["failures"])
            for item in items
        ),
        "assets_with_cross_candidate_disagreement": sum(
            bool(item["comparison"]["cross_candidate_disagreements"]) for item in items
        ),
        "assets_with_auto_novel_vs_seed_reference": sum(
            bool(item["comparison"]["auto_novel_vs_seed_reference"]) for item in items
        ),
        "assets_with_seed_reference_not_observed": sum(
            bool(item["comparison"]["seed_reference_not_observed_by_auto"]) for item in items
        ),
    }

    payload = {
        "schema_version": "visual_concept_review_queue.v0.1",
        "benchmark_id": benchmark.get("benchmark_id"),
        "benchmark_version": benchmark.get("benchmark_version"),
        "summary": summary,
        "items": items,
        "safeguards": {
            "seed_is_ground_truth": False,
            "automated_observations_are_ground_truth": False,
            "accuracy_metrics_present": False,
            "not_observed_means_absent": False,
        },
    }
    payload["queue_digest"] = canonical_digest(payload)
    return payload
