#!/usr/bin/env python3
"""Deterministic verifier for candidate-contract-review-v0."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

EXPECTED_BAD_PATHS = [
    "/protocol_fields/coco_retrieval_evaluation/evidence_refs",
    "/protocol_fields/image_preprocessing/evidence_refs",
    "/protocol_fields/imagenet1k_evaluation/evidence_refs",
    "/protocol_fields/software_runtime/evidence_refs",
    "/protocol_fields/text_tokenizer_normalization/evidence_refs",
]
EXPECTED = {
    "clean-control": {"verdict": "PASS", "defect_paths": []},
    "unsorted-c1-derived": {"verdict": "FAIL", "defect_paths": EXPECTED_BAD_PATHS},
}


def verify(candidate: Path) -> tuple[bool, str]:
    target = candidate / "review.json"
    if not target.is_file():
        return False, "review.json is missing"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"review.json is not valid JSON: {exc}"

    if set(data) != {"schema_version", "cases"} or data.get("schema_version") != 1:
        return False, "top-level shape must be exactly schema_version=1 + cases"
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) != 2:
        return False, "cases must contain exactly two entries"

    seen = {}
    for row in cases:
        if not isinstance(row, dict) or set(row) != {"id", "verdict", "defect_paths"}:
            return False, "each case must contain exactly id, verdict, defect_paths"
        case_id = row.get("id")
        if case_id in seen:
            return False, f"duplicate case id: {case_id}"
        if row.get("verdict") not in {"PASS", "FAIL", "UNKNOWN"}:
            return False, f"invalid verdict for {case_id}"
        paths = row.get("defect_paths")
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
            return False, f"defect_paths must be a string array for {case_id}"
        if paths != sorted(set(paths)):
            return False, f"defect_paths must be sorted unique for {case_id}"
        seen[case_id] = {"verdict": row["verdict"], "defect_paths": paths}

    if set(seen) != set(EXPECTED):
        return False, f"case ids mismatch: {sorted(seen)}"
    for case_id, expected in EXPECTED.items():
        if seen[case_id] != expected:
            return False, f"{case_id} mismatch: expected {expected!r}, got {seen[case_id]!r}"
    return True, "ok"


def self_test() -> None:
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        good = root_path / "good"
        bad = root_path / "bad"
        good.mkdir()
        bad.mkdir()
        (good / "review.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "cases": [
                        {"id": "clean-control", "verdict": "PASS", "defect_paths": []},
                        {
                            "id": "unsorted-c1-derived",
                            "verdict": "FAIL",
                            "defect_paths": EXPECTED_BAD_PATHS,
                        },
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (bad / "review.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "cases": [
                        {"id": "clean-control", "verdict": "FAIL", "defect_paths": []},
                        {
                            "id": "unsorted-c1-derived",
                            "verdict": "FAIL",
                            "defect_paths": EXPECTED_BAD_PATHS[:-1],
                        },
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        good_ok, _ = verify(good)
        bad_ok, _ = verify(bad)
        if not good_ok:
            raise SystemExit("self-test failed: known-good review was rejected")
        if bad_ok:
            raise SystemExit("self-test failed: known-bad review was accepted")
        print("PASS validator-review verifier accepts exact review and rejects false-positive/missed-defect control")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.candidate is None:
        parser.error("candidate path is required unless --self-test is used")
    ok, message = verify(args.candidate)
    print(("PASS " if ok else "FAIL ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
