#!/usr/bin/env python3
from copy import deepcopy

from qualification.compare_portable_receipts import compare, compare_structural


def receipt(profile_id: str, run_id: str) -> dict:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "task": {
            "id": "text-repair-v0",
            "task_class": "software.bounded-repair",
            "source_commit": "a" * 40,
            "package_digest": "sha256:" + "1" * 64,
        },
        "candidate": {
            "harness": {"name": "fixture", "version": "1"},
            "model": {"provider": "none", "id": "none"},
            "configuration_digest": "sha256:" + "2" * 64,
            "toolset": ["filesystem"],
        },
        "substrate": {
            "profile_id": profile_id,
            "profile_commit": "b" * 40,
        },
        "observation": {
            "success": True,
            "failure_class": None,
            "wall_seconds": 0.1,
            "human_interventions": 0,
            "candidate_exit_code": 0,
            "verifier_exit_code": 0,
            "timed_out": False,
            "state_changed": True,
            "failure_signals": [],
            "engine_error_types": [],
            "tool_calls": 1,
            "input_tokens": 11,
            "output_tokens": 3,
            "cache_read_tokens": 2,
            "cache_write_tokens": 0,
            "workload": {
                "model_rounds": 1,
                "resolved_models": ["contract-test"],
            },
            "cost": None,
        },
        "evidence_digest": "sha256:" + "3" * 64,
    }


native = receipt("gha-native-contract-rehearsal", "run-native")
alternate = receipt("container-local-shape-contract-rehearsal", "run-container")
alternate["observation"]["wall_seconds"] = 0.9

result = compare(native, alternate)
assert result["result"] == "PASS"
assert result["allowed_variance"]["wall_seconds"] is True

bad = deepcopy(alternate)
bad["candidate"]["configuration_digest"] = "sha256:" + "4" * 64
try:
    compare(native, bad)
except ValueError as exc:
    assert "candidate drift" in str(exc)
else:
    raise AssertionError("candidate drift did not fail closed")

bad = deepcopy(alternate)
bad["observation"]["success"] = False
try:
    compare(native, bad)
except ValueError as exc:
    assert "observation.success drift" in str(exc)
else:
    raise AssertionError("outcome drift did not fail closed")

bad = deepcopy(alternate)
bad["substrate"]["profile_id"] = native["substrate"]["profile_id"]
try:
    compare(native, bad)
except ValueError as exc:
    assert "distinct substrate profile ids" in str(exc)
else:
    raise AssertionError("same substrate id did not fail closed")

print("PASS portable receipt comparator")


stochastic_native = receipt("gha-actor", "run-stochastic-a")
stochastic_alt = receipt("local-actor", "run-stochastic-b")
stochastic_alt["observation"]["wall_seconds"] = 9.9
stochastic_alt["observation"]["workload"]["model_rounds"] = 3
stochastic_alt["observation"]["tool_calls"] = 2
structural = compare_structural(stochastic_native, stochastic_alt)
assert structural["identity_match"] is True
assert structural["structural_outcome_match"] is True

stochastic_alt["observation"]["success"] = False
stochastic_alt["observation"]["failure_class"] = "timeout"
stochastic_alt["observation"]["timed_out"] = True
structural = compare_structural(stochastic_native, stochastic_alt)
assert structural["identity_match"] is True
assert structural["structural_outcome_match"] is False
assert "success" in structural["observed_differences"]
assert "failure_class" in structural["observed_differences"]
print("PASS stochastic structural comparator preserves differences as evidence")
