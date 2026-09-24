#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

EXPECTED = {
    "c01": ("HARNESS_FAILURE", "FIX_HARNESS_AND_RETRY"),
    "c02": ("ENVIRONMENT_FAILURE", "ADJUST_RESOURCE_AND_RETRY"),
    "c03": ("AUTHORITY_REQUIRED", "REQUEST_NARROW_AUTHORITY"),
    "c04": ("PROVIDER_FAILURE", "DEFER_OR_RETRY_PROVIDER"),
    "c05": ("ACTOR_FAILURE", "PRESERVE_AND_TRY_DISTINCT_ACTOR"),
    "c06": ("VALIDATOR_FAILURE", "REPAIR_VALIDATOR_NEW_TASK_VERSION"),
    "c07": ("RECONCILIATION_FAILURE", "RECONCILE_STALE_STATE"),
    "c08": ("INCONCLUSIVE", "COLLECT_BOUNDARY_EVIDENCE"),
}

REQUIRED_EVIDENCE_SUFFIXES = {
    "c01": ["/command", "/stderr", "/guest_process_started", "/environment_entry_gates"],
    "c02": ["/package_checksum_verified", "/root_available_bytes_before_extract", "/stderr"],
    "c03": ["/required_permission", "/required_action_available", "/guest_bootstrap_ready"],
    "c04": ["/provider_admission", "/engine_error", "/model_rounds"],
    "c05": ["/model_rounds", "/tool_calls", "/required_output_present", "/verifier_self_test"],
    "c06": ["/candidate_output_schema_valid", "/verifier_self_test", "/verifier_error"],
    "c07": ["/remote_registration_exists", "/backing_host_exists", "/provider_inventory_query_completed"],
    "c08": ["/observed_events", "/event_order_known", "/retry_observation_available"],
}

ALLOWED_CLASSES = {
    "HARNESS_FAILURE",
    "PROVIDER_FAILURE",
    "ENVIRONMENT_FAILURE",
    "AUTHORITY_REQUIRED",
    "ACTOR_FAILURE",
    "VALIDATOR_FAILURE",
    "RECONCILIATION_FAILURE",
    "INCONCLUSIVE",
}

ALLOWED_PROBES = {
    "FIX_HARNESS_AND_RETRY",
    "ADJUST_RESOURCE_AND_RETRY",
    "REQUEST_NARROW_AUTHORITY",
    "DEFER_OR_RETRY_PROVIDER",
    "PRESERVE_AND_TRY_DISTINCT_ACTOR",
    "REPAIR_VALIDATOR_NEW_TASK_VERSION",
    "RECONCILE_STALE_STATE",
    "COLLECT_BOUNDARY_EVIDENCE",
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
        if evidence["source_class"] != "sanitized-derived-execution-failure-evidence":
            return False
        cases = evidence["cases"]
        if sorted(cases) != [f"c{i:02d}" for i in range(1, 9)]:
            return False
        if cases["c01"]["guest_process_started"] is not False:
            return False
        if cases["c02"]["package_checksum_verified"] is not True:
            return False
        if cases["c03"]["required_action_available"] is not False:
            return False
        if cases["c04"]["model_rounds"] != 0:
            return False
        if cases["c05"]["verifier_self_test"] != "PASS":
            return False
        if cases["c06"]["verifier_self_test"] != "FAIL_EXCEPTION":
            return False
        if cases["c07"]["backing_host_exists"] is not False:
            return False
        if cases["c08"]["event_order_known"] is not False:
            return False
        return True
    except Exception:
        return False


def check(root: Path) -> bool:
    try:
        evidence = json.loads((root / "evidence.json").read_text(encoding="utf-8"))
        if not fixture_shape_ok(evidence):
            return False

        output = json.loads((root / "triage.json").read_text(encoding="utf-8"))
        if set(output) != {"schema_version", "cases"} or output["schema_version"] != 1:
            return False
        if set(output["cases"]) != set(EXPECTED):
            return False

        for cid, (expected_class, expected_probe) in EXPECTED.items():
            row = output["cases"][cid]
            if set(row) != {"class", "evidence_refs", "next_probe"}:
                return False
            if row["class"] not in ALLOWED_CLASSES or row["class"] != expected_class:
                return False
            if row["next_probe"] not in ALLOWED_PROBES or row["next_probe"] != expected_probe:
                return False

            refs = row["evidence_refs"]
            if not isinstance(refs, list) or not refs or refs != sorted(set(refs)):
                return False

            prefix = f"evidence.json#/cases/{cid}"
            resolved = []
            for ref in refs:
                if not isinstance(ref, str) or not ref.startswith(prefix):
                    return False
                pointer = ref[len("evidence.json#"):]
                pointer_get(evidence, pointer)
                resolved.append(pointer)

            for suffix in REQUIRED_EVIDENCE_SUFFIXES[cid]:
                if f"/cases/{cid}{suffix}" not in resolved:
                    return False

        return True
    except Exception:
        return False


def good_output() -> dict:
    rows = {}
    for cid, (klass, probe) in EXPECTED.items():
        refs = [
            f"evidence.json#/cases/{cid}{suffix}"
            for suffix in REQUIRED_EVIDENCE_SUFFIXES[cid]
        ]
        rows[cid] = {
            "class": klass,
            "evidence_refs": sorted(refs),
            "next_probe": probe,
        }
    return {"schema_version": 1, "cases": rows}


def self_test() -> int:
    source_fixture = Path(__file__).parent / "fixture/evidence.json"
    fixture_text = source_fixture.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "fixture").mkdir(parents=True)
        (root / "evidence.json").write_text(fixture_text, encoding="utf-8")

        (root / "triage.json").write_text(
            json.dumps(good_output(), indent=2) + "\n", encoding="utf-8"
        )
        assert check(root)

        bad = good_output()
        bad["cases"]["c04"]["class"] = "ACTOR_FAILURE"
        (root / "triage.json").write_text(json.dumps(bad), encoding="utf-8")
        assert not check(root)

        bad = good_output()
        bad["cases"]["c06"]["class"] = "ACTOR_FAILURE"
        (root / "triage.json").write_text(json.dumps(bad), encoding="utf-8")
        assert not check(root)

        bad = good_output()
        bad["cases"]["c08"]["class"] = "PROVIDER_FAILURE"
        bad["cases"]["c08"]["next_probe"] = "DEFER_OR_RETRY_PROVIDER"
        (root / "triage.json").write_text(json.dumps(bad), encoding="utf-8")
        assert not check(root)

        bad = good_output()
        bad["cases"]["c02"]["evidence_refs"] = [
            "evidence.json#/cases/c02/stderr"
        ]
        (root / "triage.json").write_text(json.dumps(bad), encoding="utf-8")
        assert not check(root)

    print("PASS execution-failure-triage-v1 verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
