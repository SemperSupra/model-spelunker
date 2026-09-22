#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import tempfile
from pathlib import Path

CLAIM_ID = "CLAIM_SIGLIP2_B16_256_CORE"
SOURCE_HASHES = {
    "document.tex": ("05900ab2c395d94c90f4e071373d7a5617a910e04f94f37f8ce2959b3a17c1fd", 42642),
    "tables/zeroshot_main.tex": ("4e473fe2f5323fc52ad29cccbff8c7e2d0e65fe4d56c7e446e8a0750fb7d5be5", 10967),
    "README_siglip2.md": ("3c1862c16c6c75a97278fe9556482618db1d0419997eaefd4006ec9149994eef", 7763),
}
PROTOCOL_FIELDS = {
    "checkpoint_identity",
    "architecture_resolution",
    "text_tokenizer_normalization",
    "image_preprocessing",
    "imagenet1k_evaluation",
    "coco_retrieval_evaluation",
    "metric_definitions",
    "software_runtime",
    "randomness_repetition",
}
STATUSES = {
    "EXPLICIT_PAPER",
    "EXPLICIT_CHECKPOINT_README",
    "INFERABLE_WITH_EVIDENCE",
    "AMBIGUOUS",
    "CONTRADICTORY",
    "MISSING",
    "NOT_APPLICABLE",
}
READINESS = {"RUNNABLE", "PARTIAL", "BLOCKED"}
REF_RE = re.compile(
    r"^source:(document\.tex|tables/zeroshot_main\.tex|README_siglip2\.md):"
    r"L([1-9][0-9]*)(?:-L([1-9][0-9]*))?$"
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_lines(root: Path, *, enforce_hashes: bool) -> dict[str, list[str]]:
    out = {}
    for name, (expected_sha, expected_size) in SOURCE_HASHES.items():
        path = root / "fixture" / "sources" / name
        data = path.read_bytes()
        if enforce_hashes:
            if len(data) != expected_size or digest(data) != expected_sha:
                raise ValueError(f"frozen source identity mismatch: {name}")
        out[name] = data.decode("utf-8").splitlines()
    return out


def refs_ok(refs, sources: dict[str, list[str]], *, require_table: bool = False) -> bool:
    if not isinstance(refs, list) or not refs or refs != sorted(set(refs)):
        return False
    saw_table = False
    for ref in refs:
        if not isinstance(ref, str):
            return False
        match = REF_RE.match(ref)
        if not match:
            return False
        name, first, last = match.groups()
        start = int(first)
        end = int(last or first)
        if start > end or end > len(sources[name]):
            return False
        saw_table = saw_table or name == "tables/zeroshot_main.tex"
    return saw_table if require_table else True


def check(root: Path, *, enforce_hashes: bool = True) -> bool:
    try:
        sources = source_lines(root, enforce_hashes=enforce_hashes)
        output = json.loads((root / "method_ir.json").read_text(encoding="utf-8"))
        if set(output) != {"schema_version", "claim", "protocol_fields", "execution_readiness"}:
            return False
        if output["schema_version"] != 1:
            return False

        claim = output["claim"]
        if set(claim) != {"claim_id", "comparison", "evidence_refs"}:
            return False
        if claim["claim_id"] != CLAIM_ID or not refs_ok(claim["evidence_refs"], sources):
            return False

        comparison = claim["comparison"]
        if set(comparison) != {"siglip", "siglip2"}:
            return False
        for model_name in ("siglip", "siglip2"):
            row = comparison[model_name]
            if set(row) != {
                "imagenet1k_val",
                "coco_text_to_image_recall_at_1",
                "coco_image_to_text_recall_at_1",
                "evidence_refs",
            }:
                return False
            for key in (
                "imagenet1k_val",
                "coco_text_to_image_recall_at_1",
                "coco_image_to_text_recall_at_1",
            ):
                value = row[key]
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    return False
                if not math.isfinite(float(value)):
                    return False
            if not refs_ok(row["evidence_refs"], sources, require_table=True):
                return False

        fields = output["protocol_fields"]
        if set(fields) != PROTOCOL_FIELDS:
            return False
        for name in sorted(PROTOCOL_FIELDS):
            row = fields[name]
            if set(row) != {"status", "value", "evidence_refs", "absence_search"}:
                return False
            status = row["status"]
            if status not in STATUSES:
                return False
            value = row["value"]
            if value is not None and not isinstance(value, str):
                return False
            refs = row["evidence_refs"]
            absence = row["absence_search"]
            if status == "MISSING":
                if value is not None or refs != []:
                    return False
                if not isinstance(absence, str) or not absence.strip():
                    return False
            elif status == "NOT_APPLICABLE":
                if refs not in ([],):
                    return False
                if not isinstance(value, str) or not value.strip():
                    return False
                if absence is not None:
                    return False
            else:
                if not isinstance(value, str) or not value.strip():
                    return False
                if not refs_ok(refs, sources):
                    return False
                if absence is not None:
                    return False

        readiness = output["execution_readiness"]
        if set(readiness) != {"status", "blocking_fields", "notes"}:
            return False
        if readiness["status"] not in READINESS:
            return False
        blockers = readiness["blocking_fields"]
        if not isinstance(blockers, list) or blockers != sorted(set(blockers)):
            return False
        if not set(blockers) <= PROTOCOL_FIELDS:
            return False
        if not isinstance(readiness["notes"], str):
            return False

        return True
    except Exception:
        return False


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_root = root / "fixture" / "sources"
        (source_root / "tables").mkdir(parents=True)
        (source_root / "document.tex").write_text("architecture\nevaluation\n", encoding="utf-8")
        (source_root / "tables/zeroshot_main.tex").write_text(
            "header\nsiglip row\nsiglip2 row\n", encoding="utf-8"
        )
        (source_root / "README_siglip2.md").write_text("checkpoint\n", encoding="utf-8")

        fields = {}
        for name in sorted(PROTOCOL_FIELDS):
            fields[name] = {
                "status": "EXPLICIT_PAPER",
                "value": "bounded test value",
                "evidence_refs": ["source:document.tex:L1"],
                "absence_search": None,
            }
        fields["checkpoint_identity"] = {
            "status": "EXPLICIT_CHECKPOINT_README",
            "value": "checkpoint",
            "evidence_refs": ["source:README_siglip2.md:L1"],
            "absence_search": None,
        }
        fields["randomness_repetition"] = {
            "status": "MISSING",
            "value": None,
            "evidence_refs": [],
            "absence_search": "Checked all three local sources for seed/repetition details.",
        }
        good = {
            "schema_version": 1,
            "claim": {
                "claim_id": CLAIM_ID,
                "comparison": {
                    "siglip": {
                        "imagenet1k_val": 1.0,
                        "coco_text_to_image_recall_at_1": 2.0,
                        "coco_image_to_text_recall_at_1": 3.0,
                        "evidence_refs": ["source:tables/zeroshot_main.tex:L2"],
                    },
                    "siglip2": {
                        "imagenet1k_val": 2.0,
                        "coco_text_to_image_recall_at_1": 3.0,
                        "coco_image_to_text_recall_at_1": 4.0,
                        "evidence_refs": ["source:tables/zeroshot_main.tex:L3"],
                    },
                },
                "evidence_refs": ["source:document.tex:L1", "source:tables/zeroshot_main.tex:L2-L3"],
            },
            "protocol_fields": fields,
            "execution_readiness": {
                "status": "PARTIAL",
                "blocking_fields": ["randomness_repetition"],
                "notes": "test",
            },
        }
        (root / "method_ir.json").write_text(json.dumps(good), encoding="utf-8")
        assert check(root, enforce_hashes=False)

        bad = json.loads(json.dumps(good))
        bad["protocol_fields"]["randomness_repetition"]["absence_search"] = ""
        (root / "method_ir.json").write_text(json.dumps(bad), encoding="utf-8")
        assert not check(root, enforce_hashes=False)

        bad = json.loads(json.dumps(good))
        bad["claim"]["comparison"]["siglip2"]["evidence_refs"] = ["source:document.tex:L1"]
        (root / "method_ir.json").write_text(json.dumps(bad), encoding="utf-8")
        assert not check(root, enforce_hashes=False)

    print("PASS SigLIP2 Method-IR structural source-binding verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
