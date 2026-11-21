"""Independent source-only invariant and negative mutant for R7 CPU envelopes."""
import json,sys,unittest
from pathlib import Path
import importlib.util
# Unique import name: inherited direct-model parser is also named probe.py.
spec=importlib.util.spec_from_file_location("qwen_r7_payload_under_test",
                                           Path(__file__).with_name("probe.py"))
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
PROFILES,build=module.PROFILES,module.build


class EnvelopePositive(unittest.TestCase):
    def test_exact_byte_envelopes_and_only_one_variable(self):
        docs={name:build(name) for name in PROFILES}
        target=next(iter(docs.values()))
        for name,obj in docs.items():
            with self.subTest(profile=name):
                self.assertEqual(len(json.dumps(obj,separators=(",",":")).encode()),PROFILES[name])
                self.assertEqual(obj["model"],"qwen3:1.7b")
                self.assertEqual(obj["max_tokens"],256)
                self.assertEqual(obj["reasoning_effort"],"none")
                self.assertTrue(obj["stream"])
                self.assertEqual(obj["tool_choice"],"auto")
                self.assertEqual(obj["messages"][1],target["messages"][1])
                self.assertEqual(obj["tools"],target["tools"])
                self.assertIn("Neutral synthetic task-bound instruction",
                              obj["messages"][0]["content"])

                self.assertEqual([x["function"]["name"] for x in obj["tools"]],
                                  ["read_file","glob","list_directory"])

    def test_monotone_system_chars(self):
        rows=[build(key) for key in PROFILES]
        self.assertTrue(len(rows[0]["messages"][0]["content"])<
                        len(rows[1]["messages"][0]["content"])<
                        len(rows[2]["messages"][0]["content"]))


class EnvelopeNegatives(unittest.TestCase):
    def test_unsupported_profiles_fail_closed(self):
        for bad in ("", "production", "latest", "private", "r7-29kb", "gpu"):
            with self.assertRaises(ValueError):
                build(bad)

    def test_no_private_data_or_effectful_tools(self):
        for name in PROFILES:
            obj=build(name)
            s=json.dumps(obj)
            for term in ("BigMac","TrueNAS","api_key","password","Bearer","127.0.0.1",
                         "exec_shell","sudo","ssh","VALUE="):
                self.assertNotIn(term,s)
            self.assertTrue(set(x["function"]["name"] for x in obj["tools"])
                            <= {"read_file","glob","list_directory"})

if __name__=="__main__":unittest.main()
