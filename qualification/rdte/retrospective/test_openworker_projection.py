from __future__ import annotations

import json
import unittest

from qualification.rdte.retrospective.project_openworker_stdout import project_stdout


class OpenWorkerProjectionTests(unittest.TestCase):
    def test_projects_events_without_payload_content(self):
        lines = [
            "MODEL_SPELUNKER_MODEL_CALL_STARTED="
            + json.dumps({
                "index": 1,
                "requested_model": "ollama:qwen",
                "request_message_bytes": 123,
                "request_tool_schema_bytes": 456,
            }),
            "OPENWORKER_EVENT="
            + json.dumps({
                "type": "EventType.TOOL_CALL",
                "tool_calls": [{
                    "function": {
                        "name": "write_file",
                        "arguments": {"path": "secret.txt", "content": "TOP SECRET"},
                    }
                }],
                "status": "running",
            }),
            "OPENWORKER_EVENT="
            + json.dumps({
                "type": "EventType.ERROR",
                "error": "sensitive diagnostic body",
                "error_type": "BadRequestError",
            }),
            "MODEL_SPELUNKER_PROVIDER_OBSERVATIONS="
            + json.dumps([{
                "requested_model": "qwen",
                "provider": "ollama",
                "_response_id": "private-id",
                "request_message_bytes": 123,
                "request_tool_schema_bytes": 456,
                "output_text_bytes": 10,
                "reasoning_bytes": 99,
                "tool_argument_bytes": 42,
                "prompt_tokens": 20,
                "completion_tokens": 5,
            }]),
            "MODEL_SPELUNKER_USAGE="
            + json.dumps({"input": 20, "output": 5, "cache_read": 0, "cache_write": 0}),
            "OPENWORKER_SUMMARY="
            + json.dumps({
                "projection": ["read_file", "write_file"],
                "tool_calls": ["write_file"],
                "approval_count": 1,
                "approvals": [{"path": "secret.txt", "allowed": True}],
                "suppressed_speculative_batches": [{
                    "kept": {"name": "write_file", "arguments": {"secret": "x"}},
                    "suppressed": [],
                }],
                "event_counts": {"EventType.TOOL_CALL": 1, "EventType.ERROR": 1},
                "target_exists": True,
            }),
        ]
        result = project_stdout("\n".join(lines), source_ref="ephemeral:test")
        summary = result["summary"]
        self.assertEqual(summary["model_call_started_count"], 1)
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual(summary["provider_observation_count"], 1)
        self.assertEqual(summary["tool_name_counts"]["write_file"], 2)
        self.assertFalse(summary["sensitive_content_retained"])
        rendered = json.dumps(result, sort_keys=True)
        for forbidden in (
            "TOP SECRET",
            "secret.txt",
            "sensitive diagnostic body",
            "private-id",
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertIn("BadRequestError", rendered)
        self.assertIn("write_file", rendered)


if __name__ == "__main__":
    unittest.main()
