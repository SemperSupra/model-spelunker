#!/usr/bin/env python3
"""Fail-closed, source-only DOE contract for paired image conditioning (#193).

Not a renderer, GPU admission gate, runtime attestor, independent image oracle,
or claim of model quality. Does not download weights or execute ComfyUI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

SCHEMA = "conditioning-doe-plan/v1"
OBSERVATION_SCHEMA = "conditioning-doe-observations/v1"
HEX40 = re.compile(r"^[a-f0-9]{40}$")
HEX64 = re.compile(r"^[a-f0-9]{64}$")
SLUG = re.compile(r"^[a-z][a-z0-9-]{2,48}$")
MAX_SOURCE_BYTES = 128 * 1024
GENERATORS = {
    "z-image-turbo": "Tongyi-MAI/Z-Image-Turbo",
    "flux2-klein-4b": "black-forest-labs/FLUX.2-klein-4B",
}
BASE_BY_GENERATOR = {
    "z-image-turbo": "Comfy-Org/Z-Image-Turbo",
    "flux2-klein-4b": "Comfy-Org/Flux-2-Klein-4B",
}
ENCODERS = {"base", "heretic"}
HERETIC_REPO = "CCSSNE/DreamFast-qwen3-4b-heretic"
PLAN_FIELDS = {"schema", "campaign", "generator", "generator_repo", "generator_revision",
               "generator_weights_sha256", "vae_sha256", "workflow_sha256",
               "runtime_image_sha256", "comfyui_commit", "preprocess_sha256",
               "dataset_sha256", "sampler", "steps", "guidance", "width", "height",
               "quantization", "prompt_cases", "seeds", "encoders"}
ENCODER_FIELDS = {"variant", "repository", "revision", "weights_sha256", "quantization"}
PROMPT_FIELDS = {"id", "prompt_sha256"}
OBS_FIELDS = {"schema", "campaign", "plan_sha256", "runs"}
RUN_FIELDS = {"variant", "model_repository", "model_revision", "encoder_weights_sha256",
              "prompt_id", "seed", "controls_sha256", "image_sha256", "native_run_ref"}

class Denied(ValueError):
    pass

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def strict_load(path: Path, expected_sha256: str) -> dict:
    if not isinstance(expected_sha256, str) or not HEX64.fullmatch(expected_sha256):
        raise Denied("UNPINNED_INPUT")
    if path.is_symlink() or not path.is_file():
        raise Denied("INPUT_NOT_REGULAR_FILE")
    with path.open("rb") as f:
        raw = f.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise Denied("INPUT_TOO_LARGE")
    if sha(raw) != expected_sha256:
        raise Denied("INPUT_SHA_MISMATCH")
    def keys(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise Denied("DUPLICATE_JSON_FIELD")
            result[key] = value
        return result
    def nonfinite(_):
        raise Denied("NONFINITE_JSON")
    try:
        doc = json.loads(raw, object_pairs_hook=keys, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Denied("INVALID_JSON") from exc
    if not isinstance(doc, dict):
        raise Denied("TOP_LEVEL_NOT_OBJECT")
    return doc

def _hash(v):
    return isinstance(v, str) and HEX64.fullmatch(v) is not None

def _revision(v):
    return isinstance(v, str) and HEX40.fullmatch(v) is not None

def _slug(v):
    return isinstance(v, str) and SLUG.fullmatch(v) is not None

def plan_controls(plan: dict) -> dict:
    return {k: plan[k] for k in (
        "generator", "generator_repo", "generator_revision", "generator_weights_sha256",
        "vae_sha256", "workflow_sha256", "runtime_image_sha256", "comfyui_commit",
        "preprocess_sha256", "dataset_sha256", "sampler", "steps", "guidance",
        "width", "height", "quantization")}

def controls_digest(plan: dict) -> str:
    return sha(json.dumps(plan_controls(plan), sort_keys=True, separators=(",", ":")).encode())

def validate_plan(plan: dict) -> list[tuple[str, str, int]]:
    if set(plan) != PLAN_FIELDS or plan.get("schema") != SCHEMA or plan.get("campaign") != "model-spelunker-193":
        raise Denied("PLAN_SCHEMA_FIELDS")
    generator = plan["generator"]
    if generator not in GENERATORS or plan["generator_repo"] != GENERATORS[generator]:
        raise Denied("GENERATOR_NOT_ALLOWLISTED")
    for name in ("generator_revision", "comfyui_commit"):
        if not _revision(plan[name]):
            raise Denied("REVISION_UNPINNED")
    for name in ("generator_weights_sha256", "vae_sha256", "workflow_sha256",
                 "runtime_image_sha256", "preprocess_sha256", "dataset_sha256"):
        if not _hash(plan[name]):
            raise Denied("ARTIFACT_DIGEST_UNPINNED")
    if (plan["sampler"] not in ("euler", "euler_ancestral", "dpmpp_2m")
        or type(plan["steps"]) is not int or not 1 <= plan["steps"] <= 60
        or type(plan["guidance"]) not in (int, float) or not 0 <= plan["guidance"] <= 20
        or type(plan["width"]) is not int or type(plan["height"]) is not int
        or not 256 <= plan["width"] <= 1536 or not 256 <= plan["height"] <= 1536
        or plan["width"] % 16 or plan["height"] % 16
        or plan["quantization"] not in ("bf16", "fp8-e4m3")):
        raise Denied("SAMPLING_GEOMETRY_NOT_BOUNDED")
    pairs = plan["encoders"]
    if not isinstance(pairs, list) or len(pairs) != 2:
        raise Denied("ENCODER_PAIR_REQUIRED")
    seen = set()
    for entry in pairs:
        if not isinstance(entry, dict) or set(entry) != ENCODER_FIELDS:
            raise Denied("ENCODER_FIELDS")
        variant = entry["variant"]
        expected_repo = BASE_BY_GENERATOR[generator] if variant == "base" else HERETIC_REPO
        if (variant not in ENCODERS or variant in seen
            or entry["repository"] != expected_repo
            or not _revision(entry["revision"]) or not _hash(entry["weights_sha256"])
            or entry["quantization"] != plan["quantization"]):
            raise Denied("ENCODER_IDENTITY_OR_QUANTIZATION_DRIFT")
        seen.add(variant)
    if seen != set(ENCODERS):
        raise Denied("ENCODER_VARIANT_INCOMPLETE")
    cases, seeds = plan["prompt_cases"], plan["seeds"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 6:
        raise Denied("PROMPT_SET_UNBOUNDED")
    if (not isinstance(seeds, list) or not 1 <= len(seeds) <= 2
        or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds)
        or len(set(seeds)) != len(seeds)):
        raise Denied("SEED_SET_UNBOUNDED")
    names = set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != PROMPT_FIELDS
            or not _slug(case["id"]) or case["id"] in names
            or not _hash(case["prompt_sha256"])):
            raise Denied("PROMPT_CASE_INVALID")
        names.add(case["id"])
    return [(variant, case["id"], seed)
            for variant in ("base", "heretic") for case in cases for seed in seeds]

def inspect_observations(doc: dict, plan: dict, plan_sha256: str) -> dict:
    expected = validate_plan(plan)
    if (set(doc) != OBS_FIELDS or doc["schema"] != OBSERVATION_SCHEMA
        or doc["campaign"] != "model-spelunker-193" or doc["plan_sha256"] != plan_sha256
        or not isinstance(doc["runs"], list) or len(doc["runs"]) != len(expected)):
        raise Denied("OBSERVATION_SCHEMA_OR_COMPLETENESS")
    encoders = {e["variant"]: e for e in plan["encoders"]}
    control = controls_digest(plan)
    expected_set = set(expected)
    seen = set()
    native_refs = set()
    for run in doc["runs"]:
        if not isinstance(run, dict) or set(run) != RUN_FIELDS:
            raise Denied("RUN_FIELDS_OR_SELF_SCORING")
        key = (run["variant"], run["prompt_id"], run["seed"])
        if key not in expected_set or key in seen:
            raise Denied("RUN_PAIRING_DRIFT")
        seen.add(key)
        encoder = encoders[run["variant"]]
        if (run["model_repository"] != encoder["repository"]
            or run["model_revision"] != encoder["revision"]
            or run["encoder_weights_sha256"] != encoder["weights_sha256"]
            or run["controls_sha256"] != control):
            raise Denied("RUN_MODEL_OR_CONTROLS_DRIFT")
        if (not _hash(run["image_sha256"]) or not _slug(run["native_run_ref"])):
            raise Denied("OUTPUT_PROVENANCE_INCOMPLETE")
        if run["native_run_ref"] in native_refs:
            raise Denied("NATIVE_RUN_REF_REUSED")
        native_refs.add(run["native_run_ref"])
    return {
        "schema": "conditioning-doe-structure-result/v1",
        "campaign": "model-spelunker-193",
        "generator": plan["generator"], "plan_sha256": plan_sha256,
        "pair_count": len(expected) // 2, "expected_outputs": len(expected),
        "recorded_outputs": len(seen), "status": "STRUCTURE_ONLY",
        "native_inference_attested": False, "gpu_admitted": False,
        "image_bytes_verified": False, "quality_verified": False,
        "actor_qualification": "UNKNOWN_NOT_EXECUTED_BY_THIS_TOOL",
    }

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--plan-sha256", required=True)
    p.add_argument("--observations", type=Path)
    p.add_argument("--observations-sha256")
    args = p.parse_args(argv)
    try:
        plan = strict_load(args.plan, args.plan_sha256)
        matrix = validate_plan(plan)
        if args.observations is None and args.observations_sha256 is None:
            out = {"schema": "conditioning-doe-structure-result/v1",
                   "campaign": "model-spelunker-193", "generator": plan["generator"],
                   "plan_sha256": args.plan_sha256, "controls_sha256": controls_digest(plan),
                   "expected_outputs": len(matrix), "status": "PLANNED_ONLY",
                   "native_inference_attested": False, "gpu_admitted": False,
                   "quality_verified": False, "actor_qualification": "UNKNOWN"}
        elif args.observations is not None and args.observations_sha256 is not None:
            observed = strict_load(args.observations, args.observations_sha256)
            out = inspect_observations(observed, plan, args.plan_sha256)
        else:
            raise Denied("OBSERVATION_DIGEST_REQUIRED")
    except (Denied, OSError, KeyError, TypeError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Denied) else "UNTRUSTED_PROTOCOL_INPUT"
        print(json.dumps({"status": "HOLD", "reason": reason, "qualified": False}, sort_keys=True))
        return 2
    print(json.dumps(out, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
