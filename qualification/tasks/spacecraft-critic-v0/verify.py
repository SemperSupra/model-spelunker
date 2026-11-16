#!/usr/bin/env python3
"""Strict stdlib-only oracle for public synthetic spacecraft critique."""
import json
import sys
import tempfile
from pathlib import Path

EXPECTED = {
    "SOLAR-INVALID": ("INVALID", "SOLAR_POWER"),
    "SOLAR-VALID": ("VALID", "NONE"),
    "APPENDAGE-INVALID": ("INVALID", "APPENDAGE_LOAD"),
    "APPENDAGE-VALID": ("VALID", "NONE"),
    "AIRLOCK-INVALID": ("INVALID", "AIRLOCK_INTERLOCK"),
    "AIRLOCK-VALID": ("VALID", "NONE"),
    "TIMELINE-INVALID": ("INVALID", "TIMELINE_CONFLICT"),
    "TIMELINE-VALID": ("VALID", "NONE"),
    "AUTHORITY-INVALID": ("INVALID", "CANON_AUTHORITY"),
    "AUTHORITY-VALID": ("VALID", "NONE"),
    "THERMAL-INVALID": ("INVALID", "THERMAL_DEFICIT"),
    "THERMAL-VALID": ("VALID", "NONE"),
}

def check(root):
    try:
        data = json.loads((root / "cases.json").read_text(encoding="utf-8"))
        cases = data["cases"]
        if data["schema_version"] != 1 or data["source_class"] != "synthetic-public-physics-and-governance":
            return False
        if len(cases) != 12 or [c["id"] for c in cases] != list(EXPECTED):
            return False
        if any(set(c) != {"id", "domain", "facts", "question"} for c in cases):
            return False
        report = json.loads((root / "critic_report.json").read_text(encoding="utf-8"))
        if set(report) != {"schema_version", "cases"} or report["schema_version"] != 1:
            return False
        if set(report["cases"]) != set(EXPECTED):
            return False
        for index, case in enumerate(cases):
            row = report["cases"][case["id"]]
            if set(row) != {"verdict", "violation_code", "evidence_ref", "finding"}:
                return False
            if (row["verdict"], row["violation_code"]) != EXPECTED[case["id"]]:
                return False
            if row["evidence_ref"] != "cases.json#/cases/%d/facts" % index:
                return False
            if not isinstance(row["finding"], str) or len(row["finding"].strip()) < 12:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False

def self_test():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        cases = json.loads((Path(__file__).parent / "fixture/cases.json").read_text(encoding="utf-8"))
        (root / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        good = {"schema_version": 1, "cases": {
            cid: {"verdict": verdict, "violation_code": code,
                  "evidence_ref": "cases.json#/cases/%d/facts" % i,
                  "finding": "Correct according to explicit synthetic requirements."}
            for i, (cid, (verdict, code)) in enumerate(EXPECTED.items())}}
        (root / "critic_report.json").write_text(json.dumps(good), encoding="utf-8")
        assert check(root), "positive self-test did not pass"
        bad = json.loads(json.dumps(good))
        for row in bad["cases"].values():
            row["verdict"] = "VALID"
            row["violation_code"] = "NONE"
        (root / "critic_report.json").write_text(json.dumps(bad), encoding="utf-8")
        assert not check(root), "always-accept negative control was not rejected"
        bad2 = json.loads(json.dumps(good))
        bad2["cases"]["SOLAR-VALID"]["evidence_ref"] = "cases.json#/cases/0/facts"
        (root / "critic_report.json").write_text(json.dumps(bad2), encoding="utf-8")
        assert not check(root), "cross-case evidence swap not rejected"
    print("PASS spacecraft-critic-v0 deterministic verifier (+, -, swap)")
    return 0

if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
