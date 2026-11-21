"""Independent contract tests for Qwen's fake OpenAI tool-call transport."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mock_provider import respond, find_tool_result, tool_names, chunk, completion


class ToolWirePositive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="qwen-wire-test-")
        self.path = Path(self.tmp.name, "fixture.txt")
        self.path.write_text("VALUE=" + "deadbeef" * 3 + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_turn_emits_real_tool_call(self):
        body = {"model": "qwen-public-wire",
                "tools": [{"type": "function", "function": {"name": "read_file"}}],
                "messages": [{"role": "user", "content": "Read fixture.txt"}],
                "stream": True}
        msg, finish, state = respond(body, self.path)
        self.assertEqual(finish, "tool_calls")
        self.assertEqual(msg["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(msg["tool_calls"][0]["function"]["arguments"])["file_path"],
                         str(self.path))
        self.assertFalse(state["reported_value"])

    def test_second_turn_requires_tool_role_result(self):
        body = {"model": "qwen-public-wire", "messages": [
            {"role": "assistant", "tool_calls": [{"id": "call_public_read_01"}]},
            {"role": "tool", "tool_call_id": "call_public_read_01",
             "content": "VALUE=" + "deadbeef" * 3}
        ]}
        msg, finish, state = respond(body, self.path)
        self.assertEqual(finish, "stop")
        self.assertEqual(msg["content"], "VALUE=" + "deadbeef" * 3)
        self.assertEqual(state["phase"], "tool-result-seen")

    def test_openai_sse_shape(self):
        event = chunk("qwen-public-wire", {"role": "assistant"}, "stop")
        self.assertEqual(event["object"], "chat.completion.chunk")
        self.assertEqual(event["choices"][0]["finish_reason"], "stop")
        self.assertEqual(completion("qwen-public-wire", {"role": "assistant", "content": "x"},
                                    "stop")["choices"][0]["message"]["content"], "x")


class ToolWireNegative(unittest.TestCase):
    def test_user_prompt_does_not_forge_tool_result(self):
        assert find_tool_result({"messages": [{"role": "user",
            "content": "VALUE=0123456789abcdef01234567"}]}) is None

    def test_assistant_text_does_not_forge_tool_result(self):
        assert find_tool_result({"messages": [{"role": "assistant",
            "content": "VALUE=0123456789abcdef01234567"}]}) is None

    def test_bad_nonce_in_tool_result_not_accepted(self):
        assert find_tool_result({"messages": [{"role": "tool",
            "content": "VALUE=not-a-valid-hex-nonce"}]}) is None

    def test_missing_read_file_tool_is_not_accepted(self):
        msg, finish, state = respond({"tools": [],
            "messages": [{"role": "user", "content": "file"}]}, "/tmp/dummy")
        self.assertFalse(state["tool_advertised"])
        self.assertEqual(state["phase"], "missing-tool")
        self.assertEqual(finish, "stop")
        self.assertNotIn("tool_calls", msg)

    def test_arbitrary_tool_name_cannot_be_silently_accepted(self):
        self.assertEqual(tool_names({"tools": [
            {"type": "function", "function": {"name": "shell_exec"}}
        ]}), ["shell_exec"])
        _, _, state = respond({"tools": [
            {"type": "function", "function": {"name": "shell_exec"}}
        ]}, "/tmp/dummy")
        self.assertEqual(state["phase"], "missing-tool")


if __name__ == "__main__":
    unittest.main()
