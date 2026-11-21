"""Negative-mutant and independent handoff tests for public Qwen work packets."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract import validate, summarize

ORIGINAL = json.loads((Path(__file__).parent / "workset.public.json").read_text())


class ContractPositive(unittest.TestCase):
    def test_domain_packet_validator_and_no_scheduler_status(self):
        doc = validate(copy.deepcopy(ORIGINAL))
        status = summarize(doc)
        self.assertEqual(status["dispatcher"], "AGENT_DISPATCH_ONLY")
        self.assertEqual(status["planner"], "EXISTING_SUPRAGOFLOW_GO_BATCH_WAVE")
        self.assertFalse(status["dispatch_authorized"])
        self.assertEqual(status["candidate_selection"], "NOT_IMPLEMENTED")
        self.assertNotIn("candidate_ids", status)
        self.assertNotIn("cards", status)
        self.assertEqual(status["counts"]["DONE_VERIFIED"], 4)
        self.assertEqual(status["counts"]["FAILED"], 2)
        self.assertEqual(status["counts"]["BLOCKED_ADMISSION"], 2)
        self.assertEqual(status["counts"]["READY"], 0)
        self.assertEqual(status["counts"]["IN_PROGRESS"], 0)
        self.assertEqual(status["total_tasks"], 8)
        self.assertEqual(status["private_actions_minutes"], 0)

    def test_packet_budget_validation_remains_strict(self):
        for task in ORIGINAL["tasks"]:
            with self.subTest(task=task["id"]):
                self.assertLessEqual(task["budget"]["tool_calls"], 8)
                self.assertLessEqual(task["budget"]["context_tokens"], 1600)
                self.assertLessEqual(task["budget"]["wall_minutes"], 20)
                self.assertEqual(task["budget"]["private_actions_minutes"], 0)

    def test_status_does_not_turn_packet_oracle_into_execution(self):
        report = summarize(ORIGINAL)
        self.assertFalse(report["dispatch_authorized"])
        self.assertEqual(report["candidate_selection"], "NOT_IMPLEMENTED")
        self.assertEqual(report["counts"]["FAILED"], 2)


class ContractNegatives(unittest.TestCase):
    def bad(self, transform):
        mutant = copy.deepcopy(ORIGINAL)
        transform(mutant)
        with self.assertRaises(ValueError):
            validate(mutant)

    def test_duplicate_source_scope(self):
        self.bad(lambda d: d["tasks"][1].__setitem__("scope", ["qualification/qwencode_wire/client"]))

    def test_task_id_conflict(self):
        self.bad(lambda d: d["tasks"][1].__setitem__("id", d["tasks"][0]["id"]))

    def test_private_public_crossing(self):
        self.bad(lambda d: d["tasks"][0].__setitem__("classification", "PRIVATE"))

    def test_self_admitted_private(self):
        self.bad(lambda d: d["tasks"][3].__setitem__("state", "READY"))

    def test_unverified_dependency(self):
        def change(d):
            d["tasks"][7]["state"] = "IN_PROGRESS"
            d["tasks"][7]["depends_on"] = ["B03-H1-GUEST"]
        self.bad(change)

    def test_dependency_cycle(self):
        def make(d):
            d["tasks"][0]["depends_on"] = ["B02-ROUTE-HARDEN"]
            d["tasks"][1]["depends_on"] = ["B01-WIRE-DIAG"]
            d["tasks"][0]["state"] = "BLOCKED_INPUT"
            d["tasks"][1]["state"] = "BLOCKED_INPUT"
        self.bad(make)

    def test_source_sha_mutation(self):
        self.bad(lambda d: d["tasks"][0].__setitem__("source_sha", "main"))

    def test_bad_scope(self):
        self.bad(lambda d: d["tasks"][0].__setitem__("scope", ["qualification/../.ssh"]))

    def test_dle_non_github(self):
        self.bad(lambda d: d["tasks"][0].__setitem__("dle", "http://internal.invalid/token"))

    def test_budget_exceeds_weak_context(self):
        self.bad(lambda d: d["tasks"][0]["budget"].__setitem__("context_tokens", 25000))

    def test_token_budget_zero(self):
        self.bad(lambda d: d["tasks"][0]["budget"].__setitem__("tool_calls", 0))

    def test_paid_minutes(self):
        self.bad(lambda d: d["tasks"][0]["budget"].__setitem__("private_actions_minutes", 1))

    def test_new_scheduler(self):
        self.bad(lambda d: d.__setitem__("dispatcher", "NEW_BATCH_SCHEDULER"))

    def test_false_verified_status(self):
        self.bad(lambda d: d["tasks"][6].__setitem__("state", "DONE_VERIFIED"))

    def test_claim_without_oracle(self):
        def make(d):
            d["tasks"][0]["state"] = "DONE_VERIFIED"
            d["tasks"][0]["evidence"] = {
                "source_sha": d["tasks"][0]["source_sha"],
                "independent_oracle": "SELF_REPORTED",
                "run_url": "https://github.com/SemperSupra/model-spelunker/actions/runs/123456"
            }
        self.bad(make)

    def test_false_failed_status_without_receipt(self):
        self.bad(lambda d: d["tasks"][7].__setitem__("evidence", {}))

    def test_failed_claim_cannot_be_marked_as_oracle_pass(self):
        self.bad(lambda d: d["tasks"][6]["evidence"].__setitem__(
            "independent_oracle", "PASS"))

    def test_nonzero_public_host_effects(self):
        self.bad(lambda d: d.__setitem__("public_host_effects", True))


if __name__ == "__main__":
    unittest.main()
