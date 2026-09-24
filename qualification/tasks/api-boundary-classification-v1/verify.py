#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

EXPECTED = {
    "e01": ("CONFIRMED_ANONYMOUS", "NONE"),
    "e02": ("PREAUTH_BOOTSTRAP", "BOUNDED_ANONYMOUS_PROBE"),
    "e03": ("PREAUTH_BOOTSTRAP", "BOUNDED_ANONYMOUS_PROBE"),
    "e04": ("PREAUTH_BOOTSTRAP", "AUTH_BOUNDARY"),
    "e05": ("ANONYMOUS_READ_CANDIDATE", "BOUNDED_ANONYMOUS_PROBE"),
    "e06": ("ANONYMOUS_READ_CANDIDATE", "BOUNDED_ANONYMOUS_PROBE"),
    "e07": ("ANONYMOUS_READ_CANDIDATE", "BOUNDED_ANONYMOUS_PROBE"),
    "e08": ("SESSION_BOUND", "AUTH_BOUNDARY"),
    "e09": ("SESSION_BOUND", "AUTH_BOUNDARY"),
    "e10": ("SESSION_BOUND", "AUTH_BOUNDARY"),
    "e11": ("SESSION_BOUND", "AUTH_BOUNDARY"),
    "e12": ("UNKNOWN", "RECOVER_MORE_CONTEXT"),
}

REQUIRED_EVIDENCE_SUFFIXES = {
    "e01": ["/live_probe/application_success", "/live_probe/no_token"],
    "e02": ["/reachable_before_session", "/call_context"],
    "e03": ["/reachable_before_session", "/call_context"],
    "e04": ["/reachable_before_session", "/request_fields"],
    "e05": ["/session_guard_observed", "/remote_mutation", "/live_probe/attempted"],
    "e06": ["/session_guard_observed", "/remote_mutation", "/live_probe/attempted"],
    "e07": ["/session_guard_observed", "/remote_mutation", "/live_probe/attempted"],
    "e08": ["/session_guard_observed", "/reachable_before_session"],
    "e09": ["/session_guard_observed", "/remote_mutation"],
    "e10": ["/session_guard_observed", "/remote_mutation"],
    "e11": ["/session_guard_observed", "/reachable_before_session"],
    "e12": ["/conflicting_evidence"],
}

ALLOWED_CLASSES = {
    "CONFIRMED_ANONYMOUS",
    "PREAUTH_BOOTSTRAP",
    "ANONYMOUS_READ_CANDIDATE",
    "SESSION_BOUND",
    "UNKNOWN",
}
ALLOWED_NEXT = {
    "NONE",
    "BOUNDED_ANONYMOUS_PROBE",
    "AUTH_BOUNDARY",
    "RECOVER_MORE_CONTEXT",
}


def pointer_get(doc, pointer: str):
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    cur = doc
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def fixture_shape_ok(evidence: dict) -> bool:
    try:
        if evidence["schema_version"] != 1:
            return False
        if evidence["source_class"] != "sanitized-derived-mobile-app-evidence":
            return False
        endpoints = evidence["endpoints"]
        if list(sorted(endpoints)) != [f"e{i:02d}" for i in range(1, 13)]:
            return False
        if endpoints["e01"]["live_probe"]["application_success"] is not True:
            return False
        if endpoints["e04"]["reachable_before_session"] is not True:
            return False
        if endpoints["e08"]["session_guard_observed"] is not True:
            return False
        if len(endpoints["e12"]["conflicting_evidence"]) != 2:
            return False
        return True
    except Exception:
        return False


def check(root: Path) -> bool:
    try:
        evidence_path = root / "evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not fixture_shape_ok(evidence):
            return False

        output = json.loads((root / "classification.json").read_text(encoding="utf-8"))
        if set(output) != {"schema_version", "endpoints"} or output["schema_version"] != 1:
            return False
        if set(output["endpoints"]) != set(EXPECTED):
            return False

        for eid, (expected_class, expected_next) in EXPECTED.items():
            row = output["endpoints"][eid]
            if set(row) != {"class", "evidence_refs", "next_action"}:
                return False
            if row["class"] not in ALLOWED_CLASSES or row["class"] != expected_class:
                return False
            if row["next_action"] not in ALLOWED_NEXT or row["next_action"] != expected_next:
                return False
            refs = row["evidence_refs"]
            if not isinstance(refs, list) or not refs or refs != sorted(set(refs)):
                return False

            prefix = f"evidence.json#/endpoints/{eid}"
            resolved_pointers = []
            for ref in refs:
                if not isinstance(ref, str) or not ref.startswith(prefix):
                    return False
                pointer = ref[len("evidence.json#"):]
                pointer_get(evidence, pointer)
                resolved_pointers.append(pointer)

            for suffix in REQUIRED_EVIDENCE_SUFFIXES[eid]:
                required = f"/endpoints/{eid}{suffix}"
                if required not in resolved_pointers:
                    return False

        return True
    except Exception:
        return False


def good_output() -> dict:
    rows = {}
    for eid, (klass, nxt) in EXPECTED.items():
        refs = []
        for suffix in REQUIRED_EVIDENCE_SUFFIXES[eid]:
            refs.append(f"evidence.json#/endpoints/{eid}{suffix}")
        rows[eid] = {
            "class": klass,
            "evidence_refs": sorted(refs),
            "next_action": nxt,
        }
    return {"schema_version": 1, "endpoints": rows}


def self_test() -> int:
    source_fixture = Path(__file__).parent / "fixture/evidence.json"
    evidence_text = source_fixture.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "fixture").mkdir(parents=True)
        (root / "fixture/evidence.json").write_text(evidence_text, encoding="utf-8")

        (root / "classification.json").write_text(
            json.dumps(good_output(), indent=2) + "\n", encoding="utf-8"
        )
        assert check(root)

        bad = good_output()
        bad["endpoints"]["e05"]["class"] = "CONFIRMED_ANONYMOUS"
        (root / "classification.json").write_text(
            json.dumps(bad, indent=2) + "\n", encoding="utf-8"
        )
        assert not check(root)

        bad = good_output()
        bad["endpoints"]["e12"]["class"] = "ANONYMOUS_READ_CANDIDATE"
        bad["endpoints"]["e12"]["next_action"] = "BOUNDED_ANONYMOUS_PROBE"
        (root / "classification.json").write_text(
            json.dumps(bad, indent=2) + "\n", encoding="utf-8"
        )
        assert not check(root)

        bad = good_output()
        bad["endpoints"]["e01"]["evidence_refs"] = [
            "evidence.json#/endpoints/e01/path"
        ]
        (root / "classification.json").write_text(
            json.dumps(bad, indent=2) + "\n", encoding="utf-8"
        )
        assert not check(root)

    print("PASS api-boundary-classification verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
