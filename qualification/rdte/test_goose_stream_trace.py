from __future__ import annotations

import json
import unittest

from qualification.rdte.goose_stream_trace import project_stream


def line(value):
    return json.dumps(value, separators=(",", ":"))


class GooseStreamTraceTests(unittest.TestCase):
    def test_projects_tool_trajectory_without_retaining_payload_content(self):
        stdout = "\n".join([
            line({
                "type": "message",
                "message": {
                    "id": "assistant-turn-1",
                    "role": "assistant",
                    "created": 1,
                    "metadata": {
                        "userVisible": True,
                        "agentVisible": True,
                        "inference": {
                            "provider": "ollama",
                            "requestedModel": "qwen3:1.7b",
                        },
                    },
                    "content": [{
                        "type": "toolRequest",
                        "id": "call-1",
                        "toolCall": {
                            "status": "success",
                            "value": {
                                "name": "developer__shell",
                                "arguments": {"command": "cat value.txt"},
                            },
                        },
                    }],
                },
            }),
            line({
                "type": "message",
                "message": {
                    "id": "tool-result-1",
                    "role": "user",
                    "created": 2,
                    "metadata": {
                        "userVisible": False,
                        "agentVisible": True,
                    },
                    "content": [{
                        "type": "toolResponse",
                        "id": "call-1",
                        "toolResult": {
                            "status": "success",
                            "value": {
                                "content": [{"type": "text", "text": "BROKEN"}],
                                "isError": False,
                            },
                        },
                    }],
                },
            }),
            line({
                "type": "message",
                "message": {
                    "id": "assistant-turn-2",
                    "role": "assistant",
                    "created": 3,
                    "metadata": {
                        "userVisible": True,
                        "agentVisible": True,
                        "inference": {
                            "provider": "ollama",
                            "requestedModel": "qwen3:1.7b",
                        },
                    },
                    "content": [{
                        "type": "thinking",
                        "thinking": "private reasoning must not be retained",
                    }, {
                        "type": "toolRequest",
                        "id": "call-2",
                        "toolCall": {
                            "status": "success",
                            "value": {
                                "name": "developer__shell",
                                "arguments": {"command": "cat value.txt"},
                            },
                        },
                    }],
                },
            }),
            line({
                "type": "complete",
                "total_tokens": 1300,
                "input_tokens": 1100,
                "output_tokens": 200,
                "cost_usd": 0.0,
            }),
        ])

        projected = project_stream(stdout)
        summary = projected["summary"]

        self.assertEqual(summary["assistant_model_rounds"], 2)
        self.assertEqual(summary["tool_request_count"], 2)
        self.assertEqual(summary["tool_response_count"], 1)
        self.assertEqual(summary["repeated_identical_tool_call_count"], 1)
        self.assertEqual(summary["complete_usage"]["total_tokens"], 1300)
        self.assertFalse(summary["hidden_reasoning_inferred"])

        rendered = json.dumps(projected, sort_keys=True)
        self.assertNotIn("cat value.txt", rendered)
        self.assertNotIn("BROKEN", rendered)
        self.assertNotIn("private reasoning must not be retained", rendered)

    def test_preserves_tool_error_without_error_body(self):
        stdout = line({
            "type": "message",
            "message": {
                "id": "tool-result-1",
                "role": "user",
                "created": 2,
                "metadata": {"userVisible": False, "agentVisible": True},
                "content": [{
                    "type": "toolResponse",
                    "id": "call-1",
                    "toolResult": {
                        "status": "error",
                        "error": "secret-bearing diagnostic body",
                    },
                }],
            },
        })
        projected = project_stream(stdout)
        self.assertEqual(projected["summary"]["tool_error_count"], 1)
        self.assertNotIn("secret-bearing diagnostic body", json.dumps(projected))

    def test_non_json_markers_do_not_break_projection(self):
        stdout = "GOOSE banner\n" + line({
            "type": "complete",
            "total_tokens": 5,
        })
        projected = project_stream(stdout)
        self.assertEqual(projected["source"]["ignored_non_json_lines"], 1)
        self.assertEqual(projected["summary"]["complete_usage"]["total_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
