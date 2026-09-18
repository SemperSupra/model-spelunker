#!/usr/bin/env python3
"""Gate-2 control: direct-v0 versus deterministic-v0 on one identical workload."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import requests

from visual_concept_worker_core import CandidateSpec, canonical_digest, run_direct
from visual_concept_worker_deterministic import run_deterministic
from visual_concept_worker_ringer import PublicHFScorer


def candidate_from_config(cfg: dict) -> CandidateSpec:
    concepts = cfg["concepts"]
    return CandidateSpec(
        worker_framework=cfg["worker_framework"],
        framework_version=cfg["framework_version"],
        backend_family=cfg["backend_family"],
        model_id=cfg["model_id"],
        model_revision=cfg.get("model_revision"),
        concept_pack_digest=canonical_digest(concepts),
        action_policy=cfg["action_policy"],
        toolset=tuple(cfg.get("toolset", [])),
        parameters=dict(cfg.get("parameters", {})),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--direct-config", required=True)
    ap.add_argument("--deterministic-config", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    direct_cfg = json.loads(Path(args.direct_config).read_text(encoding="utf-8"))
    det_cfg = json.loads(Path(args.deterministic_config).read_text(encoding="utf-8"))
    if direct_cfg.get("public_safe") is not True or det_cfg.get("public_safe") is not True:
        raise SystemExit("Gate-2 configs must explicitly set public_safe=true")

    shared_fields = ("backend_family", "model_id", "model_revision", "image_source", "concepts")
    for field in shared_fields:
        if direct_cfg.get(field) != det_cfg.get(field):
            raise SystemExit(f"Gate-2 treatment drift in shared field: {field}")
    if direct_cfg["action_policy"] != "direct-v0":
        raise SystemExit("direct config must use direct-v0")
    if det_cfg["action_policy"] != "deterministic-v0":
        raise SystemExit("deterministic config must use deterministic-v0")

    response = requests.get(direct_cfg["image_source"], timeout=45)
    response.raise_for_status()

    with TemporaryDirectory(prefix="vcw-gate2-fixture-") as tmp:
        image_path = Path(tmp) / "fixture.png"
        image_path.write_bytes(response.content)
        scorer = PublicHFScorer(direct_cfg)
        direct_candidate = candidate_from_config(direct_cfg)
        det_candidate = candidate_from_config(det_cfg)

        start = perf_counter()
        direct = run_direct(
            scorer=scorer,
            candidate=direct_candidate,
            image_path=image_path,
            concepts=direct_cfg["concepts"],
            top_k=int(direct_candidate.parameters.get("top_k", 3)),
            execution_lane="public-ringer",
        )
        direct_seconds = perf_counter() - start

        start = perf_counter()
        deterministic = run_deterministic(
            scorer=scorer,
            candidate=det_candidate,
            image_path=image_path,
            concepts=det_cfg["concepts"],
            execution_lane="public-ringer",
        )
        deterministic_seconds = perf_counter() - start

    direct_obs = direct["observations"]
    det_whole = [
        item
        for item in deterministic["observations"]
        if item["evidence"][0]["metadata"].get("view") == "whole"
    ]
    det_regions = [
        item
        for item in deterministic["observations"]
        if item["evidence"][0]["region_xyxy"] is not None
    ]

    if len(direct_obs) != len(det_whole):
        raise SystemExit("whole-image observation count drifted between treatments")
    for left, right in zip(direct_obs, det_whole):
        if (left["label"], left["concept_id"]) != (right["label"], right["concept_id"]):
            raise SystemExit("whole-image label ordering drifted between treatments")
        le = left["evidence"][0]
        re = right["evidence"][0]
        if abs(float(le["score"]) - float(re["score"])) > 1e-7:
            raise SystemExit("whole-image score drifted between treatments")
        if abs(float(le["raw_score"]) - float(re["raw_score"])) > 1e-7:
            raise SystemExit("whole-image raw logit drifted between treatments")

    expected_region_observations = 4 * int(det_candidate.parameters.get("top_k_per_view", 3))
    if len(det_regions) != expected_region_observations:
        raise SystemExit(
            f"expected {expected_region_observations} region observations, got {len(det_regions)}"
        )
    if direct["input"]["sha256"] != deterministic["input"]["sha256"]:
        raise SystemExit("input identity drifted between treatments")
    if direct["candidate"]["candidate_digest"] == deterministic["candidate"]["candidate_digest"]:
        raise SystemExit("candidate identities must differ across action policies")

    result = {
        "schema_version": "visual_concept_worker_gate2.v0.1",
        "status": "pass",
        "input_sha256": direct["input"]["sha256"],
        "model": {
            "backend_family": direct_cfg["backend_family"],
            "model_id": direct_cfg["model_id"],
            "model_revision": direct_cfg["model_revision"],
        },
        "direct": {
            "candidate_digest": direct["candidate"]["candidate_digest"],
            "run_digest": direct["run_digest"],
            "observations": len(direct_obs),
            "seconds": direct_seconds,
            "top_labels": [item["label"] for item in direct_obs],
        },
        "deterministic": {
            "candidate_digest": deterministic["candidate"]["candidate_digest"],
            "run_digest": deterministic["run_digest"],
            "observations": len(deterministic["observations"]),
            "region_observations": len(det_regions),
            "seconds": deterministic_seconds,
            "whole_top_labels": [item["label"] for item in det_whole],
        },
        "invariants": {
            "same_input": True,
            "same_model": True,
            "whole_image_path_preserved": True,
            "candidate_identity_separated": True,
            "ground_truth_claimed": False,
            "private_content_present": False,
            "private_semantic_authority_present": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
