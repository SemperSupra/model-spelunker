#!/usr/bin/env python3
"""P0 Causal Falsification Tests: Statistical Soundness & Estimands (STAT-01, STAT-02, STAT-03)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qualification.reduce_evidence import (
    reduce_receipts,
    terminal_outcome,
    wilson_interval,
)


def make_mock_receipt(
    run_id: str,
    harness: str,
    task_class: str,
    *,
    success: bool,
    verifier_exit: int,
    candidate_exit: int,
    timed_out: bool,
    admitted_completion: bool | None = None,
    failure_signals: list[str] | None = None,
    model_rounds: int | None = None,
) -> dict:
    obs = {
        "success": success,
        "verifier_exit_code": verifier_exit,
        "candidate_exit_code": candidate_exit,
        "timed_out": timed_out,
        "termination_class": "semantic-success" if success else ("timeout-censored" if timed_out else "semantic-failure"),
        "failure_signals": failure_signals or [],
        "workload": {"model_rounds": model_rounds},
    }
    if admitted_completion is not None:
        obs["admitted_completion"] = admitted_completion
        obs["artifact_valid"] = (verifier_exit == 0)
        obs["candidate_completed"] = (candidate_exit == 0 and not timed_out)
        obs["within_wall_budget"] = not timed_out

    return {
        "run_id": run_id,
        "task": {"id": f"task-{task_class}", "task_class": task_class},
        "candidate": {"harness": {"name": harness}, "model": {"id": "qwen3-coder-30b"}, "toolset": ["dev"]},
        "substrate": {"profile_id": "test-substrate"},
        "observation": obs,
    }


def test_stat_01_wilson_denominators_and_null_telemetry() -> None:
    """STAT-01: Correct Wilson denominators and null != 0 for unobserved telemetry."""
    # 4/4
    w44 = wilson_interval(4, 4)
    assert w44 is not None
    assert round(w44["lower_95"], 4) == 0.5101
    assert round(w44["upper_95"], 4) == 1.0000

    # 3/4
    w34 = wilson_interval(3, 4)
    assert w34 is not None
    assert round(w34["lower_95"], 4) == 0.3006
    assert round(w34["upper_95"], 4) == 0.9544

    # 3/3
    w33 = wilson_interval(3, 3)
    assert w33 is not None
    assert round(w33["lower_95"], 4) == 0.4385
    assert round(w33["upper_95"], 4) == 1.0000

    # 0/4
    w04 = wilson_interval(0, 4)
    assert w04 is not None
    assert round(w04["lower_95"], 4) == 0.0000
    assert round(w04["upper_95"], 4) == 0.4899

    print("PASS: STAT-01 Wilson denominators and intervals verified")


def test_stat_02_verifier_success_with_timeout_censoring() -> None:
    """STAT-02: Verifier success with timeout/nonzero candidate exit separates artifact validity from completion."""
    # Simulating Pi boundary trial 3: verifier passed (0), but candidate timed out (124)
    r_pass = [
        make_mock_receipt(f"pi-{i}", "pi", "bounded-debugging", success=True, verifier_exit=0, candidate_exit=0, timed_out=False, admitted_completion=True)
        for i in range(1, 4)
    ]
    r_timeout = make_mock_receipt(
        "pi-4",
        "pi",
        "bounded-debugging",
        success=False,
        verifier_exit=0,  # Verifier passed!
        candidate_exit=124,
        timed_out=True,  # Process timed out!
        admitted_completion=False,
        failure_signals=["timeout"],
    )
    receipts = r_pass + [r_timeout]

    envelopes = reduce_receipts(receipts)
    assert len(envelopes) == 1
    ev = envelopes[0]["evidence"]

    # Must report 3 passes, 0 fails, 1 censored, 0 incomplete
    assert ev["validated_pass"] == 3
    assert ev["validated_fail"] == 0
    assert ev["censored"] == 1
    assert ev["incomplete"] == 0

    # Operational rate: 3/4 -> [0.3006, 0.9544]
    op_w = ev["operational_success_rate"]["wilson_95"]
    assert round(op_w["lower_95"], 4) == 0.3006
    assert round(op_w["upper_95"], 4) == 0.9544

    # Conditional semantic rate: 3/3 -> [0.4385, 1.0000]
    cond_w = ev["conditional_semantic_rate"]["wilson_95"]
    assert round(cond_w["lower_95"], 4) == 0.4385
    assert round(cond_w["upper_95"], 4) == 1.0000

    print("PASS: STAT-02 Separate artifact validity and timeout censoring")


def test_stat_03_aider_operational_failures_and_semantic_status() -> None:
    """STAT-03: Aider protocol failures are visible operational failures with semantic status NOT_ESTIMABLE."""
    receipts = [
        make_mock_receipt(
            f"aider-{i}",
            "aider",
            "bounded-repair",
            success=False,
            verifier_exit=1,
            candidate_exit=0,
            timed_out=False,
            admitted_completion=False,
            failure_signals=["false-completion"],
            model_rounds=None,
        )
        for i in range(1, 5)
    ]

    envelopes = reduce_receipts(receipts)
    assert len(envelopes) == 1
    ev = envelopes[0]["evidence"]

    # Operational failure must be recorded (0 passes, 4 failures)
    assert ev["validated_pass"] == 0
    assert ev["validated_fail"] == 4
    assert ev["incomplete"] == 0
    assert ev["censored"] == 0

    # Operational Wilson interval: 0/4 -> [0.0, 0.4899]
    op_w = ev["operational_success_rate"]["wilson_95"]
    assert op_w["estimate"] == 0.0
    assert round(op_w["upper_95"], 4) == 0.4899

    # Conditional semantic status: NOT_ESTIMABLE
    assert ev["conditional_semantic_rate"]["status"] == "NOT_ESTIMABLE"
    assert ev["conditional_semantic_rate"]["wilson_95"] is None
    assert ev["failure_taxonomy"]["protocol_failures"] == 4

    print("PASS: STAT-03 Aider operational failures and NOT_ESTIMABLE semantic status")


def test_stat_hist_historical_portfolio_invariants() -> None:
    """STAT-HIST: Verify byte-level digests and taxonomy invariants across 48 historical receipts."""
    import glob
    import hashlib
    import json
    import re

    evidence_dir = ROOT / "qualification" / "evidence"
    files = sorted([
        f for f in evidence_dir.glob("windows-*.json")
        if "reduction" not in f.name and not f.name.endswith(".diag.json")
    ])

    assert len(files) == 48, f"Expected exactly 48 historical receipts, got {len(files)}"

    # 1. Byte-level digest invariant across raw receipts
    h = hashlib.sha256()
    digest_re = re.compile(r"^sha256:[0-9a-f]{64}$")
    rows = []
    for f in files:
        data_bytes = f.read_bytes().replace(b"\r\n", b"\n")
        h.update(data_bytes)
        row = json.loads(data_bytes.decode("utf-8"))
        assert digest_re.match(row["evidence_digest"]), f"Invalid digest in {f.name}"
        rows.append(row)

    expected_combined_sha256 = "fca5624602c99211dffab94c2a32c15db20e27c8e91a4ef34eab4708f961b496"
    assert h.hexdigest() == expected_combined_sha256, (
        f"Byte-level historical receipt integrity violated: {h.hexdigest()} != {expected_combined_sha256}"
    )

    # 2. Portfolio reduction assertions
    envelopes = reduce_receipts(rows)
    assert len(envelopes) == 12, f"Expected 12 envelopes (6 actors x 2 tasks), got {len(envelopes)}"

    by_actor_task = {
        (env["actor"]["candidate"]["harness"]["name"], env["task_class"]): env
        for env in envelopes
    }

    # Aider assertions: validated_fail=4, incomplete=0, validator_invalid=0, protocol_failures=4
    for task_class in ("software.bounded-repair", "software.bounded-debugging"):
        aider_env = by_actor_task[("aider", task_class)]
        ev = aider_env["evidence"]
        assert ev["validated_pass"] == 0
        assert ev["validated_fail"] == 4
        assert ev["incomplete"] == 0
        assert ev["censored"] == 0
        assert ev["failure_taxonomy"]["protocol_failures"] == 4
        assert ev["failure_taxonomy"]["protocol_cause_inferred"] is True
        assert ev["failure_taxonomy"]["validator_invalid"] == 0
        assert ev["operational_success_rate"]["passes"] == 0
        assert ev["operational_success_rate"]["trials"] == 4
        assert ev["conditional_semantic_rate"]["status"] == "NOT_ESTIMABLE"
        assert ev["conditional_semantic_rate"]["wilson_95"] is None

    # Pi assertions
    pi_repair = by_actor_task[("pi", "software.bounded-repair")]["evidence"]
    assert pi_repair["validated_pass"] == 4
    assert pi_repair["validated_fail"] == 0

    pi_debug = by_actor_task[("pi", "software.bounded-debugging")]["evidence"]
    assert pi_debug["validated_pass"] == 3
    assert pi_debug["validated_fail"] == 0
    assert pi_debug["censored"] == 1
    assert pi_debug["failure_taxonomy"]["timeout_censored"] == 1

    # Goose assertions
    goose_repair = by_actor_task[("goose", "software.bounded-repair")]["evidence"]
    assert goose_repair["validated_pass"] == 4
    assert goose_repair["validated_fail"] == 0

    goose_debug = by_actor_task[("goose", "software.bounded-debugging")]["evidence"]
    assert goose_debug["validated_pass"] == 3
    assert goose_debug["validated_fail"] == 1
    assert goose_debug["failure_taxonomy"]["semantic_failures"] == 1

    print("PASS: STAT-HIST 48-trial historical portfolio byte digests and reduction invariants")


if __name__ == "__main__":
    test_stat_01_wilson_denominators_and_null_telemetry()
    test_stat_02_verifier_success_with_timeout_censoring()
    test_stat_03_aider_operational_failures_and_semantic_status()
    test_stat_hist_historical_portfolio_invariants()
    print("ALL P0 Statistical Soundness tests PASS (STAT-01..STAT-03, STAT-HIST)")
