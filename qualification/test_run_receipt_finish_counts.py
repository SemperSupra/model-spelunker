"""The receipt schema must accept native finish evidence already emitted by the runner."""

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from qualification.run_task import workload_summary


class FinishReasonSchemaTests(unittest.TestCase):
    def setUp(self):
        schema = json.loads((Path(__file__).parent / "run-receipt.schema.json").read_text())
        self.validator = Draft202012Validator(
            schema["properties"]["observation"]["properties"]["workload"]
        )
        self.observed = workload_summary([
            {"finish_reason": "tool_calls"},
            {"finish_reason": "stop"},
            {"finish_reason": "stop"},
        ])

    def test_actual_runner_output_is_schema_valid(self):
        self.assertEqual(self.observed["provider_finish_reason_counts"], {"tool_calls": 1, "stop": 2})
        self.validator.validate(self.observed)

    def test_unobserved_stays_absent_and_valid(self):
        unobserved = workload_summary([{}])
        self.assertNotIn("provider_finish_reason_counts", unobserved)
        self.validator.validate(unobserved)

    def test_invalid_counts_and_unknown_fields_still_rejected(self):
        for counts in ({"stop": -1}, {"stop": True}, {"stop": 1.5}, {"stop": "1"}, {"": 1}):
            with self.subTest(counts=counts):
                invalid = copy.deepcopy(self.observed)
                invalid["provider_finish_reason_counts"] = counts
                self.assertTrue(list(self.validator.iter_errors(invalid)))
        invalid = {**self.observed, "unrecognized_workload_field": 0}
        self.assertTrue(list(self.validator.iter_errors(invalid)))


if __name__ == "__main__":
    unittest.main()
