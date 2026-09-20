#!/usr/bin/env python3
from qualification.reduce_evidence import reduce_receipts


def receipt(run_id: str, success: bool, *, model_rounds: int | None = None):
    observation = {"success": success}
    if model_rounds is not None:
        observation.update({
            "timed_out": False,
            "candidate_exit_code": 0,
            "workload": {"model_rounds": model_rounds},
        })
    return {
        "run_id": run_id,
        "task": {"id": "text-repair-v0", "task_class": "software.bounded-repair"},
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
