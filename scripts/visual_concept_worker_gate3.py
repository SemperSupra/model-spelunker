#!/usr/bin/env python3
"""Gate 3: wire the bounded active controller to a real visual model/tool."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import requests

from visual_active_integration import run_active_real
from visual_concept_worker_core import CandidateSpec, canonical_digest, run_direct
from visual_concept_worker_deterministic import run_deterministic
from visual_concept_worker_ringer import PublicHFScorer


def candidate_from_config(cfg: dict) -> CandidateSpec:
    return CandidateSpec(
        worker_framework=cfg["worker_framework"],
        framework_version=cfg["framework_version"],
        backend_family=cfg["backend_family"],
        model_id=cfg["model_id"],
        model_revision=cfg.get("model_revision"),
        concept_pack_digest=canonical_digest(cfg["concepts"]),
        action_policy=cfg["action_policy"],
        toolset=tuple(cfg.get("toolset", [])),
        parameters=dict(cfg.get("parameters", {})),
    )


def evidence_signature(item: dict) -> tuple:
    e=item["evidence"][0]
    return (
        item["label"], item.get("concept_id"),
        round(float(e["score"]), 8) if e.get("score") is not None else None,
        round(float(e["raw_score"]), 8) if e.get("raw_score") is not None else None,
        e.get("region_xyxy"),
    )


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--direct-config", required=True)
    ap.add_argument("--deterministic-config", required=True)
    ap.add_argument("--active-config", required=True)
    ap.add_argument("--output", required=True)
    args=ap.parse_args()

    cfgs=[
        json.loads(Path(args.direct_config).read_text(encoding="utf-8")),
        json.loads(Path(args.deterministic_config).read_text(encoding="utf-8")),
        json.loads(Path(args.active_config).read_text(encoding="utf-8")),
    ]
    direct_cfg, det_cfg, active_cfg=cfgs
    for cfg in cfgs:
        if cfg.get("public_safe") is not True:
            raise SystemExit("all Gate-3 configs must explicitly set public_safe=true")
    shared=("backend_family","model_id","model_revision","image_source","concepts")
    for field in shared:
        if not (direct_cfg.get(field)==det_cfg.get(field)==active_cfg.get(field)):
            raise SystemExit(f"Gate-3 treatment drift in shared field: {field}")
    if direct_cfg["action_policy"]!="direct-v0": raise SystemExit("direct treatment drift")
    if det_cfg["action_policy"]!="deterministic-v0": raise SystemExit("deterministic treatment drift")
    if active_cfg["action_policy"]!="active-v0": raise SystemExit("active treatment drift")

    response=requests.get(direct_cfg["image_source"],timeout=45)
    response.raise_for_status()
    with TemporaryDirectory(prefix="vcw-gate3-") as tmp:
        image_path=Path(tmp)/"fixture.png"
        image_path.write_bytes(response.content)
        scorer=PublicHFScorer(direct_cfg)
        direct_candidate=candidate_from_config(direct_cfg)
        det_candidate=candidate_from_config(det_cfg)
        active_candidate=candidate_from_config(active_cfg)

        start=perf_counter()
        direct=run_direct(
            scorer=scorer,candidate=direct_candidate,image_path=image_path,
            concepts=direct_cfg["concepts"],
            top_k=int(direct_candidate.parameters.get("top_k",3)),
            execution_lane="public-ringer",
        )
        direct_seconds=perf_counter()-start

        start=perf_counter()
        deterministic=run_deterministic(
            scorer=scorer,candidate=det_candidate,image_path=image_path,
            concepts=det_cfg["concepts"],execution_lane="public-ringer",
        )
        deterministic_seconds=perf_counter()-start

        start=perf_counter()
        active=run_active_real(
            candidate=active_candidate,image_path=image_path,initial_manifest=direct,
            scorer=scorer,concepts=active_cfg["concepts"],
        )
        active_seconds=perf_counter()-start
        active_repeat=run_active_real(
            candidate=active_candidate,image_path=image_path,initial_manifest=direct,
            scorer=scorer,concepts=active_cfg["concepts"],
        )

    direct_obs=direct["observations"]
    det_whole=[x for x in deterministic["observations"] if x["evidence"][0]["metadata"].get("view")=="whole"]
    active_obs=active["worker_run"]["observations"]
    initial_active=active_obs[:len(direct_obs)]
    added_active=active_obs[len(direct_obs):]

    if [evidence_signature(x) for x in direct_obs] != [evidence_signature(x) for x in det_whole]:
        raise SystemExit("deterministic whole-image path drifted from direct baseline")
    if [evidence_signature(x) for x in direct_obs] != [evidence_signature(x) for x in initial_active]:
        raise SystemExit("active initial evidence drifted from direct baseline")
    if active["actions_executed"] != 1 or active["stop_reason"] != "budget_exhausted":
        raise SystemExit(f"expected exactly one bounded active probe, got {active['actions_executed']} / {active['stop_reason']}")
    if len(added_active) != int(active_candidate.parameters["top_k_per_probe"]):
        raise SystemExit("active probe observation count mismatch")
    if not all(x["evidence"][0]["region_xyxy"] is not None for x in added_active):
        raise SystemExit("active probe evidence is not region-grounded")
    if active["execution_digest"] != active_repeat["execution_digest"]:
        raise SystemExit("active execution digest is not reproducible")
    if active["worker_run"]["run_digest"] != active_repeat["worker_run"]["run_digest"]:
        raise SystemExit("active worker run digest is not reproducible")
    ids={
        direct["candidate"]["candidate_digest"],
        deterministic["candidate"]["candidate_digest"],
        active["worker_run"]["candidate"]["candidate_digest"],
    }
    if len(ids)!=3:
        raise SystemExit("treatment candidate identities are not distinct")

    whole_scores=[float(x["evidence"][0]["score"]) for x in direct_obs]
    margin=whole_scores[0]-whole_scores[1]
    threshold=float(active_candidate.parameters["margin_threshold"])
    if not margin < threshold:
        raise SystemExit(f"fixture no longer exercises active branch: margin={margin} threshold={threshold}")

    result={
        "schema_version":"visual_concept_worker_gate3.v0.1",
        "status":"pass",
        "input_sha256":direct["input"]["sha256"],
        "model":{
            "backend_family":direct_cfg["backend_family"],
            "model_id":direct_cfg["model_id"],
            "model_revision":direct_cfg["model_revision"],
        },
        "decision":{
            "policy":active_candidate.parameters["policy"],
            "top2_margin":margin,
            "threshold":threshold,
            "actions_executed":active["actions_executed"],
            "stop_reason":active["stop_reason"],
            "parent_observation_id":active["action_trace"][0]["parent_observation_id"],
        },
        "direct":{
            "candidate_digest":direct["candidate"]["candidate_digest"],
            "run_digest":direct["run_digest"],
            "observations":len(direct_obs),
            "model_views":1,
            "seconds":direct_seconds,
        },
        "deterministic":{
            "candidate_digest":deterministic["candidate"]["candidate_digest"],
            "run_digest":deterministic["run_digest"],
            "observations":len(deterministic["observations"]),
            "model_views":5,
            "seconds":deterministic_seconds,
        },
        "active":{
            "candidate_digest":active["worker_run"]["candidate"]["candidate_digest"],
            "worker_run_digest":active["worker_run"]["run_digest"],
            "execution_digest":active["execution_digest"],
            "observations":len(active_obs),
            "added_region_observations":len(added_active),
            "model_views":2,
            "seconds":active_seconds,
        },
        "invariants":{
            "same_input":True,
            "same_model_and_revision":True,
            "same_concept_pack":True,
            "direct_evidence_preserved_in_deterministic":True,
            "direct_evidence_preserved_in_active":True,
            "active_action_observation_dependent":True,
            "active_action_budget_bounded":True,
            "active_evidence_region_grounded":True,
            "active_execution_reproducible":True,
            "candidate_identity_separated":True,
            "ground_truth_claimed":False,
            "performance_claim":False,
            "private_content_present":False,
            "private_semantic_authority_present":False,
        },
    }
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
