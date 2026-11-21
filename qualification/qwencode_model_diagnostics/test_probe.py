import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe import parse_stream, parse_nonstream, valid_tool, request_payload


class ParserPositive(unittest.TestCase):
    def test_stream_handles_split_name_and_arguments(self):
        packets = [
            {"choices":[{"delta":{"tool_calls":[{
                "index":0,"function":{"name":"read_","arguments":"{\"file_"}}]},
                "finish_reason":None}]},
            {"choices":[{"delta":{"tool_calls":[{
                "index":0,"function":{"name":"file","arguments":"path\":\"fixture.txt\"}"}}]},
                "finish_reason":None}]},
            {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}
        ]
        raw="".join("data: "+json.dumps(o)+"\n\n" for o in packets)+"data: [DONE]\n\n"
        calls, finish, deltas=parse_stream(raw)
        self.assertEqual(finish,"tool_calls")
        self.assertEqual(deltas,3)
        self.assertTrue(valid_tool(calls))

    def test_nonstream_tools_without_content(self):
        msg={"choices":[{"message":{
            "role":"assistant","content":None,"tool_calls":[{
              "function":{"name":"read_file","arguments":'{"file_path":"fixture.txt"}'}
            }]}, "finish_reason":"tool_calls"}]}
        calls,reason=parse_nonstream(json.dumps(msg))
        self.assertTrue(valid_tool(calls))
        self.assertEqual(reason,"tool_calls")
        self.assertIsNone(msg["choices"][0]["message"]["content"])

    def test_explicit_tool_schema_bounded(self):
        req=request_payload(True)
        self.assertEqual(req["model"],"qwen3:1.7b")
        self.assertEqual(req["reasoning_effort"],"none")
        self.assertEqual(req["tools"][0]["function"]["name"],"read_file")
        self.assertLessEqual(req["max_tokens"],256)


class ParserRedteam(unittest.TestCase):
    def test_empty_sse_not_a_pass(self):
        self.assertFalse(valid_tool(parse_stream("data: [DONE]\n\n")[0]))
    def test_content_only_does_not_imply_tool_call(self):
        raw='data: '+json.dumps({"choices":[{"delta":{"content":"fixture.txt"},"finish_reason":"stop"}]})+'\n\n'
        self.assertFalse(valid_tool(parse_stream(raw)[0]))
    def test_invalid_args_denied(self):
        self.assertFalse(valid_tool([{"name":"read_file","arguments":"not-json"}]))
    def test_wrong_file_denied(self):
        self.assertFalse(valid_tool([{"name":"read_file","arguments":'{"file_path":"/etc/passwd"}'}]))
    def test_unrelated_tool_denied(self):
        self.assertFalse(valid_tool([{"name":"shell_exec","arguments":'{"file_path":"fixture.txt"}'}]))
    def test_other_model_context_not_injected(self):
        req=request_payload(False)
        self.assertNotIn("api_key",json.dumps(req))
        self.assertNotIn("BigMac",json.dumps(req))
        self.assertNotIn("TrueNAS",json.dumps(req))
        self.assertFalse(req["stream"])


if __name__=="__main__":
    unittest.main()
