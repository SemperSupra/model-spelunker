#!/usr/bin/env python3
from qualification.reduce_evidence import reduce_receipts


def receipt(
    run_id: str,
    success: bool,
    *,
    model_rounds: int | None = None,
    engine_error: str | None = None,
    timed_out: bool = False,
    candidate_exit_code: int = 0,
    task_class: str = "software.bounded-repair",
):
    observation = {"success": success}
    if model_rounds is not None:
        observation.update({
            "timed_out": timed_out,
            "candidate_exit_code": candidate_exit_code,
            "workload": {"model_rounds": model_rounds},
        })
    if engine_error is not None:
        observation["engine_error_types"] = [engine_error]
        observation["failure_signals"] = ["engine-error-event"]
    return {
        "run_id": run_id,
        "task": {"id": "fixture-task", "task_class": task_class},
        "candidate": {
            "harness": {"name": "fixture", "version": "1"},
            "model": {"provider": "none", "id": "none"},
            "configuration_digest": "sha256:" + "0" * 64,
            "toolset": ["filesystem"],
        },
        "substrate": {
            "profile_id": "fixture",
            "profile_commit": "0" * 40,
        },
        "observation": observation,
    }


rows = [receipt("run-a", True), receipt("run-b", True)]
envelopes = reduce_receipts(rows)
assert len(envelopes) == 1
env = envelopes[0]
assert env["task_class"] == "software.bounded-repair"
assert env["evidence_pattern"] == "PASS_ONLY"
assert env["evidence"]["validated_pass"] == 2
assert env["ksa_evidence"]["skills"]["bounded_change_execution"] == "REPEATED_EVIDENCE"

rows.append(receipt("run-c", False))
env = reduce_receipts(rows)[0]
assert env["evidence_pattern"] == "MIXED"
assert env["ksa_evidence"]["abilities"]["scope_discipline"] == "MIXED_EVIDENCE"

negative = reduce_receipts([receipt("run-d", False)])[0]
assert negative["evidence_pattern"] == "FAIL_ONLY"
assert negative["ksa_evidence"]["skills"]["bounded_change_execution"] == "NEGATIVE_BOUNDARY_OBSERVED"

print("PASS evidence reducer")


incomplete = reduce_receipts([receipt("run-e", False, model_rounds=0)])[0]
assert incomplete["evidence_pattern"] == "NO_TERMINAL_EVIDENCE"
assert incomplete["evidence"]["validated_fail"] == 0
assert incomplete["evidence"]["incomplete"] == 1
assert incomplete["ksa_evidence"]["skills"]["bounded_change_execution"] == "INSUFFICIENT_EVIDENCE"

attempted_failure = reduce_receipts([receipt("run-f", False, model_rounds=2)])[0]
assert attempted_failure["evidence_pattern"] == "FAIL_ONLY"
assert attempted_failure["evidence"]["validated_fail"] == 1


partial_engine_failure = reduce_receipts(
    [receipt("run-g", False, model_rounds=1, engine_error="BadRequestError")]
)[0]
assert partial_engine_failure["evidence_pattern"] == "NO_TERMINAL_EVIDENCE"
assert partial_engine_failure["evidence"]["validated_fail"] == 0
assert partial_engine_failure["evidence"]["incomplete"] == 1
assert (
    partial_engine_failure["ksa_evidence"]["skills"]["bounded_change_execution"]
    == "INSUFFICIENT_EVIDENCE"
)


zero_round_timeout = reduce_receipts(
    [receipt("run-h", False, model_rounds=0, timed_out=True, candidate_exit_code=124)]
)[0]
assert zero_round_timeout["evidence_pattern"] == "NO_TERMINAL_EVIDENCE"
assert zero_round_timeout["evidence"]["validated_fail"] == 0
assert zero_round_timeout["evidence"]["incomplete"] == 1

reconciliation_failure = reduce_receipts(
    [receipt("run-i", False, model_rounds=4, task_class="repository.state-reconciliation")]
)[0]
assert reconciliation_failure["evidence_pattern"] == "FAIL_ONLY"
assert (
    reconciliation_failure["ksa_evidence"]["skills"]["repository_state_reconciliation"]
    == "NEGATIVE_BOUNDARY_OBSERVED"
)
assert (
    reconciliation_failure["ksa_evidence"]["abilities"]["unknown_preservation"]
    == "NEGATIVE_BOUNDARY_OBSERVED"
)


validator_failure = receipt("run-validator", False, model_rounds=2)
validator_failure["observation"]["failure_class"] = "validator-error"
validator_failure["observation"]["failure_signals"] = ["validator-error"]
env = reduce_receipts([validator_failure])[0]
assert env["evidence_pattern"] == "NO_TERMINAL_EVIDENCE"
assert env["evidence"]["validated_fail"] == 0
assert env["evidence"]["incomplete"] == 1

duplicate = receipt("run-dup", True)
env = reduce_receipts([duplicate, duplicate])[0]
assert env["evidence"]["reps"] == 1
assert env["evidence"]["validated_pass"] == 1

divergent = receipt("run-dup", False)
try:
    reduce_receipts([duplicate, divergent])
except ValueError as exc:
    assert "divergent receipt" in str(exc)
else:
    raise AssertionError("divergent duplicate run_id did not fail closed")

print("PASS duplicate and validator-error reducer controls")
