from __future__ import annotations

import json
import unittest
from pathlib import Path

from qualification.rdte.retrospective.reduce_trace import TraceError, reduce_manifest
from qualification.rdte.retrospective.run_batch import run_batch

ROOT = Path(__file__).resolve().parent
MANIFESTS = ROOT / "manifests"


def load(name: str) -> dict:
    return json.loads((MANIFESTS / name).read_text(encoding="utf-8"))


class BenchTests(unittest.TestCase):
    def test_noop_followup(self):
        result = reduce_manifest(load("jules-q4o-same-session-noop.json"))
        self.assertIn("NO_MATERIAL_ADAPTATION_AFTER_FEEDBACK", result["signals"])
        self.assertEqual(result["noop_mutation_count"], 1)
        self.assertEqual(result["feedback_results"][0]["seconds_to_next_mutation"], 89.0)

    def test_missing_followup(self):
        result = reduce_manifest(load("jules-q4o-feedback-unknown.json"))
        self.assertIn("UNKNOWN_FEEDBACK_ADAPTATION", result["signals"])
        self.assertIsNone(result["feedback_results"][0]["seconds_to_next_mutation"])

    def test_provider_reject(self):
        result = reduce_manifest(load("jules-provider-reject.json"))
        self.assertTrue(result["pre_execution_provider_failure"])
        self.assertEqual(result["dispatch_to_first_reject_seconds"], 5.0)

    def test_completion_validation_mismatch(self):
        result = reduce_manifest(load("codex-false-completion.json"))
        self.assertIn("TOOL_FAILURE", result["signals"])
        self.assertIn("COMPLETION_VALIDATION_MISMATCH", result["signals"])

    def test_censored_trace(self):
        result = reduce_manifest(load("goose-censored-historical.json"))
        self.assertEqual(result["trace_disposition"], "CENSORED")
        self.assertIn("UNKNOWN_GAP_PRESENT", result["signals"])

    def test_source_binding(self):
        manifest = load("jules-provider-reject.json")
        manifest["events"][0]["source_ref"] = "not-declared"
        with self.assertRaises(TraceError):
            reduce_manifest(manifest)

    def test_batch(self):
        batch, markdown = run_batch(MANIFESTS)
        self.assertEqual(batch["rep_count"], 5)
        self.assertEqual(set(batch["actor_family_counts"]), {"codex", "goose", "jules"})
        self.assertFalse(batch["qualification_state_changed"])
        self.assertIn("PRE_EXECUTION_PROVIDER_FAILURE", markdown)


if __name__ == "__main__":
    unittest.main()
