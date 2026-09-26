#!/usr/bin/env python3
"""Verifier for the first freshness-driven maintenance triage interview."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

EXPECTED_UNKNOWNS = {
    "exact upstream contract change",
    "whether a source-code repair is required",
}


def verify(candidate: Path) -> tuple[bool, str]:
    path = candidate / "triage.json"
    if not path.is_file():
        return False, "triage.json is missing"
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"triage.json is not valid JSON: {exc}"

    checks = [
        (result.get("failure_plane") == "upstream-component", "failure_plane must be upstream-component"),
        (result.get("actor_failure") is False, "actor_failure must remain false"),
        (result.get("disposition") == "diagnose-before-repair", "disposition must diagnose before repair"),
        (result.get("next_experiment") == "reproduce-resolution-contract", "next_experiment must reproduce the resolution contract"),
        (result.get("human_escalation") is False, "human escalation is not yet earned"),
        (not result.get("root_cause"), "unsupported root cause must remain unset/null"),
        (set(result.get("unknowns") or []) == EXPECTED_UNKNOWNS, "required unknowns were not preserved exactly"),
    ]
    for ok, message in checks:
        if not ok:
            return False, message
    return True, "ok"


def self_test() -> None:
    good_result = {
        "failure_plane": "upstream-component",
        "actor_failure": False,
        "disposition": "diagnose-before-repair",
        "next_experiment": "reproduce-resolution-contract",
        "human_escalation": False,
        "root_cause": None,
        "unknowns": sorted(EXPECTED_UNKNOWNS),
    }
    bad_result = dict(good_result)
    bad_result["actor_failure"] = True
    bad_result["root_cause"] = "the actor broke it"

    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        good = root_path / "good"
        bad = root_path / "bad"
        good.mkdir()
        bad.mkdir()
        (good / "triage.json").write_text(json.dumps(good_result), encoding="utf-8")
        (bad / "triage.json").write_text(json.dumps(bad_result), encoding="utf-8")
        if not verify(good)[0]:
            raise SystemExit("self-test failed: known-good output rejected")
        if verify(bad)[0]:
            raise SystemExit("self-test failed: known-bad output accepted")
    print("PASS maintenance triage verifier accepts supported attribution and rejects actor blame/root-cause invention")


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
