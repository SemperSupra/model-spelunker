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
                "summary": {"event_count": 4},
                "events": [
                    {
                        "type": "message",
                        "message_id": "a1",
                        "role": "assistant",
                        "content": [{"kind": "thinking"}],
                    },
                    {
                        "type": "message",
                        "message_id": "a1",
                        "role": "assistant",
                        "content": [
                            {"kind": "thinking"},
                            {"kind": "tool_request", "tool_name": "write_file"},
                        ],
                    },
                    {
                        "type": "message",
                        "message_id": "u1",
                        "role": "user",
                        "content": [
                            {"kind": "tool_response", "response_status": "success"}
                        ],
                    },
                    {
                        "type": "message",
                        "message_id": "a2",
                        "role": "assistant",
                        "content": [{"kind": "text"}],
                    },
                ],
            }))
            ow.write_text(json.dumps({
                "summary": {"event_count": 4, "model_call_started_count": 1},
                "events": [
                    {"type": "EventType.TURN_START", "tool_names": []},
                    {
                        "type": "EventType.ASSISTANT_MESSAGE",
                        "tool_names": ["write_file"],
                    },
                    {"type": "EventType.TOOL_PROPOSED", "tool_names": []},
                    {"type": "EventType.TOOL_FINISHED", "tool_names": []},
                ],
            }))
            codex.write_text(json.dumps({
                "summary": {"completion_validation_mismatch": True},
                "process_events": [
                    {"kind": "function_call_output"},
                    {"kind": "tool_call", "tool_name": "write_stdin"},
                    {"kind": "tool_call_completed"},
                ],
            }))

            result = analyze(goose, ow, [codex])
            self.assertEqual(result["family_count"], 3)
            self.assertFalse(
                result["interpretation"]["universal_event_ontology_claimed"]
            )

            goose_result = result["families"][0]
            self.assertEqual(goose_result["message_group_count"], 3)
            self.assertEqual(goose_result["native_token_count"], 3)
            self.assertEqual(
                goose_result["anchor_variant"],
                ["TOOL_REQUEST", "TOOL_RESULT"],
            )

            openworker_result = result["families"][1]
            self.assertEqual(
                openworker_result["anchor_variant"],
                ["TOOL_REQUEST", "TOOL_RESULT"],
            )

            codex_result = result["families"][2]
            self.assertEqual(
                codex_result["anchor_variant"],
                ["TOOL_REQUEST", "TOOL_RESULT", "VALIDATION_MISMATCH"],
            )

            self.assertIn("TOOL_REQUEST", result["anchor_vocabulary"])
            self.assertIn("TOOL_RESULT", result["anchor_vocabulary"])
            self.assertIn(
                "TOOL_REQUEST",
                result["anchors_observed_in_multiple_families"],
            )
            self.assertIn(
                "TOOL_RESULT",
                result["anchors_observed_in_multiple_families"],
            )


if __name__ == "__main__":
    unittest.main()
