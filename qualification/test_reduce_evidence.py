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
    ksa_requirements: list[dict[str, str]] | None = None,
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
    task = {"id": "fixture-task", "task_class": task_class}
    if ksa_requirements:
        task["ksa_requirements"] = ksa_requirements
    return {
        "run_id": run_id,
        "task": task,
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
assert env["schema_version"] == 2
assert env["task_class"] == "software.bounded-repair"
assert env["evidence_pattern"] == "PASS_ONLY"
assert env["evidence"]["validated_pass"] == 2
assert env["ksa_evidence"]["skills"]["bounded_change_execution"] == "REPEATED_EVIDENCE"

# Legacy task mappings are composite. A task failure does not localize a KSA negative
# or cancel already-observed positive KSA evidence.
rows.append(receipt("run-c", False))
env = reduce_receipts(rows)[0]
assert env["evidence_pattern"] == "MIXED"
assert env["ksa_evidence"]["abilities"]["scope_discipline"] == "REPEATED_EVIDENCE"
assert (
    env["ksa_evidence_detail"]["abilities"]["scope_discipline"][
        "nonisolating_task_negative_trials"
    ]
    == 1
)

negative = reduce_receipts([receipt("run-d", False)])[0]
assert negative["evidence_pattern"] == "FAIL_ONLY"
assert (
    negative["ksa_evidence"]["skills"]["bounded_change_execution"]
    == "INSUFFICIENT_EVIDENCE"
)
assert (
    negative["ksa_evidence_detail"]["skills"]["bounded_change_execution"][
        "nonisolating_task_negative_trials"
    ]
    == 1
)

print("PASS conservative legacy/composite KSA reduction")


isolating = [
    {
        "family": "skills",
        "name": "fault_localization",
        "evidence_role": "isolating",
    }
]
isolating_negative = reduce_receipts(
    [receipt("run-isolating-neg", False, model_rounds=2, ksa_requirements=isolating)]
)[0]
assert (
    isolating_negative["ksa_evidence"]["skills"]["fault_localization"]
    == "NEGATIVE_BOUNDARY_OBSERVED"
)
assert (
    isolating_negative["ksa_evidence_detail"]["skills"]["fault_localization"][
        "isolating_negative_trials"
    ]
    == 1
)

isolating_mixed = reduce_receipts(
    [
        receipt("run-isolating-pass", True, ksa_requirements=isolating),
        receipt("run-isolating-fail", False, model_rounds=2, ksa_requirements=isolating),
    ]
)[0]
assert isolating_mixed["ksa_evidence"]["skills"]["fault_localization"] == "MIXED_EVIDENCE"

supporting = [
    {
        "family": "abilities",
        "name": "scope_discipline",
        "evidence_role": "supporting",
    }
]
supporting_pass = reduce_receipts(
    [receipt("run-supporting-pass", True, ksa_requirements=supporting)]
)[0]
assert (
    supporting_pass["ksa_evidence"]["abilities"]["scope_discipline"]
    == "SUPPORTING_EVIDENCE"
)
print("PASS explicit isolating/composite/supporting KSA roles")


incomplete = reduce_receipts([receipt("run-e", False, model_rounds=0)])[0]
assert incomplete["evidence_pattern"] == "NO_TERMINAL_EVIDENCE"
assert incomplete["evidence"]["validated_fail"] == 0
assert incomplete["evidence"]["incomplete"] == 1
assert incomplete["ksa_evidence"] == {}

attempted_failure = reduce_receipts([receipt("run-f", False, model_rounds=2)])[0]
assert attempted_failure["evidence_pattern"] == "FAIL_ONLY"
assert attempted_failure["evidence"]["validated_fail"] == 1


partial_engine_failure = reduce_receipts(
    [receipt("run-g", False, model_rounds=1, engine_error="BadRequestError")]
)[0]
assert partial_engine_failure["evidence_pattern"] == "NO_TERMINAL_EVIDENCE"
assert partial_engine_failure["evidence"]["validated_fail"] == 0
assert partial_engine_failure["evidence"]["incomplete"] == 1
assert partial_engine_failure["ksa_evidence"] == {}


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
    == "INSUFFICIENT_EVIDENCE"
)
assert (
    reconciliation_failure["ksa_evidence"]["abilities"]["unknown_preservation"]
    == "INSUFFICIENT_EVIDENCE"
)
assert (
    reconciliation_failure["ksa_evidence_detail"]["abilities"]["unknown_preservation"][
        "nonisolating_task_negative_trials"
    ]
    == 1
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


# Scientific characterization controls: timeout is performance censoring, not semantic failure.
censored = reduce_receipts(
    [receipt("run-timeout", False, model_rounds=2, timed_out=True, candidate_exit_code=124)]
)[0]
assert censored["evidence_pattern"] == "NO_TERMINAL_EVIDENCE"
assert censored["evidence"]["validated_fail"] == 0
assert censored["evidence"]["censored"] == 1
assert censored["evidence"]["semantic_trials"] == 0
assert censored["evidence"]["success_interval_wilson_95"] is None

mixed_tasks = [
    receipt("run-task-a", True),
    receipt("run-task-b", True),
]
mixed_tasks[1]["task"]["id"] = "fixture-task-2"
env = reduce_receipts(mixed_tasks)[0]
assert env["evidence"]["unique_task_instances"] == 2
assert env["evidence"]["semantic_trials"] == 2
interval = env["evidence"]["success_interval_wilson_95"]
assert interval is not None
assert interval["estimate"] == 1.0
assert 0.0 < interval["lower_95"] < 1.0
assert interval["upper_95"] == 1.0
print("PASS characterization censoring and uncertainty controls")


inflight_timeout = receipt(
    "run-inflight-timeout",
    False,
    model_rounds=0,
    timed_out=True,
    candidate_exit_code=124,
)
inflight_timeout["observation"]["workload"]["model_calls_started"] = 1
env = reduce_receipts([inflight_timeout])[0]
assert env["evidence_pattern"] == "NO_TERMINAL_EVIDENCE"
assert env["evidence"]["validated_fail"] == 0
assert env["evidence"]["censored"] == 1
assert env["evidence"]["incomplete"] == 0
assert env["evidence"]["semantic_trials"] == 0
print("PASS in-flight timeout censoring")


iteration_censored = receipt(
    "run-iteration-censored",
    False,
    model_rounds=4,
    candidate_exit_code=0,
)
iteration_censored["observation"]["termination_class"] = "iteration-censored"
iteration_censored["observation"]["failure_signals"] = ["iteration-limit", "state-unchanged"]
iteration_censored["observation"]["workload"]["model_calls_started"] = 4
env = reduce_receipts([iteration_censored])[0]
assert env["evidence_pattern"] == "NO_TERMINAL_EVIDENCE"
assert env["evidence"]["validated_fail"] == 0
assert env["evidence"]["censored"] == 1
assert env["evidence"]["semantic_trials"] == 0
assert env["ksa_evidence"] == {}
print("PASS iteration-limit censoring")
