#!/usr/bin/env python3
"""Independent, offline paired VLM output comparison for Model Spelunker #191.

Consumes a pre-frozen oracle and two model-output receipts; never invokes a
model, opens an image, or counts a self-reported runtime as qualified.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

PAIRS = {
    "qwen3-vl-2b": ("Qwen/Qwen3-VL-2B-Instruct", "heretic-org/Qwen-3-VL-2B-Instruct-heretic"),
    "lfm2.5-vl-3b": ("LiquidAI/LFM2.5-VL-3B", "heretic-org/LFM2.5-VL-3B-heretic"),
    "minicpm-v-4.6": ("openbmb/MiniCPM-V-4.6", "heretic-org/MiniCPM-V-4.6-heretic"),
    "qwen3-vl-8b": ("Qwen/Qwen3-VL-8B-Instruct", "heretic-org/Qwen-3-VL-8B-Instruct-heretic"),
}
HEX64 = re.compile(r"^[a-f0-9]{64}$")
HEX40 = re.compile(r"^[a-f0-9]{40}$")
CASE_ID = re.compile(r"^[a-z][a-z0-9-]{3,63}$")
CASE_CLASSES = frozenset({
    "count", "spatial", "ocr", "pose_defect", "clothing_contact",
    "temporal_order", "motion_contact", "unknown_visibility", "instruction_boundary"
})
LANGUAGES = frozenset({"en", "de", "th"})
MAX_JSON_BYTES = 256 * 1024
MAX_CASES = 64

class Denied(ValueError):
    pass

def _dedup(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise Denied("DUPLICATE_JSON_FIELD")
        result[key] = value
    return result

def _nonfinite(_: str):
    raise Denied("NONFINITE_JSON")

def read_pinned(path: Path, digest: str) -> dict:
    if not isinstance(digest, str) or not HEX64.fullmatch(digest):
        raise Denied("DIGEST_PIN_REQUIRED")
    if path.is_symlink() or not path.is_file():
        raise Denied("INPUT_FILE_UNTRUSTED")
    with path.open("rb") as f:
        data = f.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise Denied("INPUT_TOO_LARGE")
    if hashlib.sha256(data).hexdigest() != digest:
        raise Denied("INPUT_DIGEST_MISMATCH")
    try:
        obj = json.loads(data, object_pairs_hook=_dedup, parse_constant=_nonfinite)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Denied("INVALID_JSON") from exc
    if not isinstance(obj, dict):
        raise Denied("INPUT_NOT_OBJECT")
    return obj

def _hash(value):
    return isinstance(value, str) and bool(HEX64.fullmatch(value.removeprefix("sha256:")))

def _value(value):
    return (type(value) is bool or (type(value) is int and 0 <= value <= 10000)
            or (isinstance(value, str) and 0 < len(value) <= 96 and
                all(c.isprintable() for c in value)))

def _cases(oracle: dict) -> dict:
    if oracle.get("schema") != "vlm-oracle/v1" or oracle.get("campaign") != "model-spelunker-191":
        raise Denied("ORACLE_SCHEMA_OR_CAMPAIGN")
    records = oracle.get("cases")
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_CASES:
        raise Denied("ORACLE_CASE_COUNT")
    cases = {}
    for c in records:
        if not isinstance(c, dict) or set(c) != {
            "id", "task_class", "language", "modality", "frame_count",
            "media_sha256", "prompt_sha256", "reference", "expected"
        }:
            raise Denied("ORACLE_CASE_FIELDS")
        ident = c["id"]
        if not isinstance(ident, str) or not CASE_ID.fullmatch(ident) or ident in cases:
            raise Denied("ORACLE_CASE_ID")
        if (c["task_class"] not in CASE_CLASSES or c["language"] not in LANGUAGES or
            c["modality"] not in ("image", "video") or
            type(c["frame_count"]) is not int or not 1 <= c["frame_count"] <= 32 or
            (c["modality"] == "image" and c["frame_count"] != 1) or
            (c["modality"] == "video" and c["frame_count"] < 2) or
            (c["task_class"] in ("temporal_order", "motion_contact") and c["modality"] != "video") or
            not _hash(c["media_sha256"]) or not _hash(c["prompt_sha256"]) or
            not isinstance(c["reference"], str) or not c["reference"].startswith("public-synthetic:") or
            len(c["reference"]) > 128 or not _value(c["expected"])):
            raise Denied("ORACLE_CASE_INVALID")
        cases[ident] = c
    return cases

def _observations(doc: dict, treatment: str, model_id: str, revision: str, cases: dict) -> tuple[dict, dict]:
    allowed = {"schema", "campaign", "treatment", "model_id", "model_revision",
               "runtime_id", "sampler_sha256", "preprocessing_sha256",
               "vision_route_declared", "outputs"}
    if set(doc) != allowed:
        # The observation producer must not carry the sealed independent oracle,
        # arbitrary model/private data or a second hidden scoring channel.
        raise Denied("OUTPUT_RECEIPT_FIELDS_OR_ORACLE_LEAK")
    if (doc.get("schema") != "vlm-observation/v1" or doc.get("campaign") != "model-spelunker-191" or
        doc.get("treatment") != treatment or doc.get("model_id") != model_id or
        doc.get("model_revision") != revision or
        not _hash(doc.get("sampler_sha256")) or not _hash(doc.get("preprocessing_sha256")) or
        not isinstance(doc.get("runtime_id"), str) or
        not 1 <= len(doc["runtime_id"]) <= 96 or
        doc.get("vision_route_declared") is not True):
        raise Denied("MODEL_IDENTITY_OR_VISION_ROUTE_UNVERIFIED")
    records = doc.get("outputs")
    if not isinstance(records, list) or len(records) != len(cases):
        raise Denied("OUTPUT_COUNT_MISMATCH")
    outputs = {}
    for row in records:
        if not isinstance(row, dict) or set(row) != {
            "id", "media_sha256", "prompt_sha256", "frame_count",
            "modality", "language", "status", "answer", "evidence_frames"
        }:
            raise Denied("OUTPUT_FIELDS")
        key = row["id"]
        if not isinstance(key, str) or key not in cases or key in outputs:
            raise Denied("OUTPUT_ID_MISMATCH")
        c = cases[key]
        for field in ("media_sha256", "prompt_sha256", "frame_count", "modality", "language"):
            if row[field] != c[field] or type(row[field]) is not type(c[field]):
                raise Denied("INPUT_TREATMENT_DRIFT")
        indices = row["evidence_frames"]
        if (not isinstance(indices, list) or len(indices) > c["frame_count"] or
            any(type(i) is not int or not 0 <= i < c["frame_count"] for i in indices) or
            len(set(indices)) != len(indices)):
            raise Denied("FRAME_REFERENCE_INVALID")
        if row["status"] == "ANSWER":
            if not _value(row["answer"]) or not indices:
                raise Denied("ANSWER_UNGROUNDED")
            if c["modality"] == "video" and len(indices) < 2:
                raise Denied("TEMPORAL_EVIDENCE_INSUFFICIENT")
        elif row["status"] == "ABSTAIN":
            if row["answer"] is not None or indices:
                raise Denied("ABSTENTION_INVALID")
        else:
            raise Denied("STATUS_INVALID")
        outputs[key] = row
    return outputs, {key: doc[key] for key in ("runtime_id", "sampler_sha256", "preprocessing_sha256")}

def assess(pair: str, oracle: dict, base: dict, heretic: dict, base_sha: str, heretic_sha: str,
           oracle_digest: str, base_digest: str, heretic_digest: str) -> dict:
    if pair not in PAIRS or any(not isinstance(sha, str) or not HEX40.fullmatch(sha) for sha in (base_sha, heretic_sha)):
        raise Denied("MODEL_PAIR_OR_REVISION_UNPINNED")
    cases = _cases(oracle)
    names = PAIRS[pair]
    base_rows, base_ctx = _observations(base, "base", names[0], base_sha, cases)
    heretic_rows, heretic_ctx = _observations(heretic, "heretic", names[1], heretic_sha, cases)
    if base_ctx != heretic_ctx:
        raise Denied("HARNESS_SAMPLER_OR_PREPROCESSING_CONFOUNDED")
    per_class = defaultdict(lambda: {"cases": 0, "base_exact": 0, "heretic_exact": 0,
                                    "base_abstentions": 0, "heretic_abstentions": 0})
    for key, c in cases.items():
        bucket = per_class[c["task_class"] + "/" + c["language"] + "/" + c["modality"]]
        bucket["cases"] += 1
        for treatment, rows in (("base", base_rows), ("heretic", heretic_rows)):
            row = rows[key]
            if row["status"] == "ABSTAIN":
                bucket[treatment + "_abstentions"] += 1
            elif type(row["answer"]) is type(c["expected"]) and row["answer"] == c["expected"]:
                bucket[treatment + "_exact"] += 1
    return {
        "schema": "vlm-paired-source-score/v1", "campaign": "model-spelunker-191",
        "pair": pair, "oracle_digest": oracle_digest,
        "base_receipt_digest": base_digest, "heretic_receipt_digest": heretic_digest,
        "case_count": len(cases), "task_class_language_modality_scores": dict(sorted(per_class.items())),
        "verdict": "STRUCTURAL_ORACLE_SCORE_ONLY",
        "model_inference_attested": False, "visual_ground_truth_proven": False,
        "physical_anatomy_certified": False,
        "runtime_admission": "NOT_ESTABLISHED_BY_OUTPUT_RECEIPTS",
        "actor_qualification": "UNKNOWN_REQUIRES_INDEPENDENT_RUNTIME_AND_HUMAN_REVIEW",
    }

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pair", required=True, choices=sorted(PAIRS))
    for name in ("oracle", "base", "heretic"):
        p.add_argument("--" + name, required=True, type=Path)
        p.add_argument("--" + name + "-sha256", required=True)
    p.add_argument("--base-revision", required=True)
    p.add_argument("--heretic-revision", required=True)
    a = p.parse_args(argv)
    try:
        oracle = read_pinned(a.oracle, a.oracle_sha256)
        base = read_pinned(a.base, a.base_sha256)
        heretic = read_pinned(a.heretic, a.heretic_sha256)
        result = assess(a.pair, oracle, base, heretic, a.base_revision, a.heretic_revision,
                        a.oracle_sha256, a.base_sha256, a.heretic_sha256)
    except (Denied, OSError, TypeError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Denied) else "SOURCE_INPUT_INVALID"
        print(json.dumps({"verdict": "HOLD", "reason": reason,
                          "actor_qualification": "UNKNOWN"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
