"""The receipt schema must accept native finish evidence already emitted by the runner."""

import copy
import json
from pathlib import Path
import unittest

from jsonschema.validators import validator_for

from qualification.run_task import workload_summary


class FinishReasonSchemaTests(unittest.TestCase):
    def setUp(self):
        schema = json.loads((Path(__file__).parent / "run-receipt.schema.json").read_text())
        validator_type = validator_for(schema)
        validator_type.check_schema(schema)
        self.validator = validator_type(
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
        for observations in ([], [{}], [{"finish_reason": None}], [{"finish_reason": ""}]):
            with self.subTest(observations=observations):
                unobserved = workload_summary(observations)
                self.assertNotIn("provider_finish_reason_counts", unobserved)
                self.assertNotIn("provider_finish_reason_unknown_count", unobserved)
                self.validator.validate(unobserved)

    def test_unknown_reasons_are_counted_without_raw_values(self):
        marker = "unexpected-provider-value-not-for-export"
        unknown = workload_summary([{"finish_reason": marker}])
        self.assertNotIn("provider_finish_reason_counts", unknown)
        self.assertEqual(unknown["provider_finish_reason_unknown_count"], 1)
        self.assertNotIn(marker, json.dumps(unknown))
        self.validator.validate(unknown)

    def test_mixed_known_and_unknown_observations_are_valid(self):
        mixed = workload_summary([
            {"finish_reason": "stop"}, {"finish_reason": "unexpected-a"},
            {"finish_reason": "stop"}, {"finish_reason": "unexpected-b"},
        ])
        self.assertEqual(mixed["provider_finish_reason_counts"], {"stop": 2})
        self.assertEqual(mixed["provider_finish_reason_unknown_count"], 2)
        self.validator.validate(mixed)

    def test_invalid_counts_and_unknown_fields_still_rejected(self):
        for counts in ({"stop": -1}, {"stop": True}, {"stop": 1.5}, {"stop": "1"}, {"": 1}):
            with self.subTest(counts=counts):
                invalid = copy.deepcopy(self.observed)
                invalid["provider_finish_reason_counts"] = counts
                self.assertTrue(list(self.validator.iter_errors(invalid)))
        invalid = {**self.observed, "unrecognized_workload_field": 0}
        self.assertTrue(list(self.validator.iter_errors(invalid)))

    def test_invalid_unknown_counts_still_rejected(self):
        for count in (-1, True, 1.5, "1", None):
            with self.subTest(count=count):
                invalid = {**self.observed, "provider_finish_reason_unknown_count": count}
                self.assertTrue(list(self.validator.iter_errors(invalid)))


if __name__ == "__main__":
    unittest.main()
