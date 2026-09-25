from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qualification.rdte.retrospective.analyze_process_variants import analyze


class ProcessVariantTests(unittest.TestCase):
    def test_preserves_native_vocabulary_and_conservative_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            goose = root / "goose.json"
            ow = root / "ow.json"
            codex = root / "codex.json"

            goose.write_text(json.dumps({
                "summary": {"event_count": 2},
                "events": [
                    {"type": "message", "role": "assistant", "content": [
                        {"kind": "tool_request", "tool_name": "write_file"}
                    ]},
                    {"type": "message", "role": "user", "content": [
                        {"kind": "tool_response", "response_status": "success"}
                    ]},
                ],
            }))
            ow.write_text(json.dumps({
                "summary": {"event_count": 2, "model_call_started_count": 1},
                "events": [
                    {"type": "EventType.TOOL_CALL", "tool_names": ["write_file"]},
                    {"type": "EventType.TOOL_RESULT", "tool_names": []},
                ],
            }))
            codex.write_text(json.dumps({
                "summary": {"completion_validation_mismatch": True},
                "process_events": [
                    {"kind": "tool_call", "tool_name": "write_stdin"},
                    {"kind": "tool_call_completed"},
                ],
            }))

            result = analyze(goose, ow, [codex])
            self.assertEqual(result["family_count"], 3)
            self.assertFalse(result["interpretation"]["universal_event_ontology_claimed"])
            self.assertIn("TOOL_REQUEST", result["anchor_vocabulary"])
            self.assertIn("TOOL_RESULT", result["common_anchor_vocabulary"])
            self.assertEqual(result["families"][0]["family"], "goose")
            self.assertEqual(result["families"][1]["family"], "openworker")
            self.assertEqual(result["families"][2]["family"], "codex")


if __name__ == "__main__":
    unittest.main()
