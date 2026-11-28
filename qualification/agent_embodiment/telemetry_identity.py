"""Generic bounded identity coverage for native Qwen JSON log records.

No identifiers or payloads leave the caller; matching keys is not causal proof.
"""
from collections import Counter
import unittest


def identity(value):
    return isinstance(value, str) and 0 < len(value) <= 512 and bool(value.strip())


class IdentityCoverage:
    def __init__(self, expected_call_id=None):
        self.requests = Counter()
        self.responses = Counter()
        self.missing_request = self.missing_response = 0
        self.tools = self.tool_missing = self.tool_matching = 0
        self.expected_call_id = expected_call_id

    def observe(self, attrs):
        if not isinstance(attrs, dict):
            return
        event = attrs.get("event.name")
        if event in ("qwen-code.api_request", "qwen-code.api_response"):
            key = tuple(attrs.get(k) for k in ("session.id", "prompt_id", "execution_id"))
            request = event == "qwen-code.api_request"
            if not all(identity(v) for v in key):
                if request:
                    self.missing_request += 1
                else:
                    self.missing_response += 1
                return
            (self.requests if request else self.responses)[key] += 1
        elif event == "qwen-code.tool_call":
            self.tools += 1
            key = attrs.get("call_id")
            if not identity(key):
                self.tool_missing += 1
            elif key == self.expected_call_id and attrs.get("function_name") == "read_file" and attrs.get("success") is True:
                self.tool_matching += 1

    def summary(self):
        keys = self.requests.keys() | self.responses.keys()
        paired = sum(self.requests[k] == self.responses[k] == 1 for k in keys)
        ambiguous = sum(self.requests[k] > 1 or self.responses[k] > 1 for k in keys)
        return {"unique_api_id_pairs": paired,
                "unmatched_api_id_keys": len(keys) - paired - ambiguous,
                "ambiguous_api_id_keys": ambiguous,
                "api_requests_missing_identity": self.missing_request,
                "api_responses_missing_identity": self.missing_response,
                "tool_records": self.tools,
                "tool_records_missing_call_id": self.tool_missing,
                "expected_successful_tool_id_records": self.tool_matching,
                "unique_expected_tool_record": self.tools == self.tool_matching == 1}


class IdentityTests(unittest.TestCase):
    def test_exact_pair_and_no_raw_values(self):
        c = IdentityCoverage("synthetic-call-secret")
        base = {"session.id": "session-secret", "prompt_id": "prompt-secret", "execution_id": "execution-secret"}
        c.observe(dict(base, **{"event.name": "qwen-code.api_request"}))
        c.observe(dict(base, **{"event.name": "qwen-code.api_response"}))
        c.observe({"event.name": "qwen-code.tool_call", "call_id": "synthetic-call-secret", "function_name": "read_file", "success": True})
        r = c.summary()
        self.assertEqual(r["unique_api_id_pairs"], 1)
        self.assertTrue(r["unique_expected_tool_record"])
        self.assertNotIn("secret", str(r))

    def test_wrong_or_missing_ids_and_duplicates(self):
        base = {"session.id": "s", "prompt_id": "p", "execution_id": "e"}
        for key, value in (("session.id", "other"), ("prompt_id", "other"), ("execution_id", "other"), ("execution_id", None), ("execution_id", []), ("execution_id", True)):
            with self.subTest(key=key, value=value):
                c = IdentityCoverage()
                c.observe(dict(base, **{"event.name": "qwen-code.api_request"}))
                c.observe(dict(base, **{key: value, "event.name": "qwen-code.api_response"}))
                self.assertEqual(c.summary()["unique_api_id_pairs"], 0)
        c = IdentityCoverage()
        for event in ("qwen-code.api_request", "qwen-code.api_request", "qwen-code.api_response"):
            c.observe(dict(base, **{"event.name": event}))
        self.assertEqual(c.summary()["ambiguous_api_id_keys"], 1)
        self.assertEqual(c.summary()["unique_api_id_pairs"], 0)

    def test_tool_match_not_inferred(self):
        base = {"event.name": "qwen-code.tool_call", "call_id": "issued", "function_name": "read_file", "success": True}
        for key, value in (("call_id", "wrong"), ("call_id", None), ("function_name", "other"), ("success", False), ("success", 1)):
            c = IdentityCoverage("issued")
            c.observe(dict(base, **{key: value}))
            self.assertFalse(c.summary()["unique_expected_tool_record"])
        c = IdentityCoverage("issued")
        c.observe(base)
        c.observe(base)
        self.assertFalse(c.summary()["unique_expected_tool_record"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
