"""Public-only source and strict single-variable crossover assertions."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from diagnose import PROFILES,SYSTEM_CHARS,make_profile


def names(p):
    return [t["function"]["name"] for t in p["tools"]]


class CrossoverPositive(unittest.TestCase):
    def test_constant_runtime_model_request_and_user_task(self):
        docs={k:make_profile(k) for k in PROFILES}
        for k,v in docs.items():
            with self.subTest(profile=k):
                self.assertEqual(v["model"],"qwen3:1.7b")
                self.assertEqual(v["reasoning_effort"],"none")
                self.assertTrue(v["stream"])
                self.assertEqual(v["max_tokens"],256)
                self.assertEqual(v["tool_choice"],"auto")
                self.assertEqual(names(v)[0],"read_file")
                self.assertEqual(v["messages"][1],docs["short-three"]["messages"][1])

    def test_short_three_only_increases_tool_count(self):
        p=make_profile("short-three")
        q=make_profile("medium-three")
        self.assertEqual(len(p["tools"]),3)
        self.assertEqual(len(q["tools"]),3)
        self.assertEqual(p["tools"],q["tools"])
        self.assertLess(len(p["messages"][0]["content"]),200)

    def test_medium_one_and_three_exact_same_system(self):
        p=make_profile("medium-one")
        q=make_profile("medium-three")
        self.assertEqual(len(p["tools"]),1)
        self.assertEqual(len(q["tools"]),3)
        self.assertEqual(p["messages"][0]["content"],q["messages"][0]["content"])
        self.assertEqual(len(p["messages"][0]["content"]),SYSTEM_CHARS)
        self.assertEqual(p["tools"][0],q["tools"][0])


class CrossoverRedteam(unittest.TestCase):
    def test_no_private_host_or_remote_endpoint_or_credential(self):
        for profile in PROFILES:
            p=make_profile(profile)
            doc=json.dumps(p)
            self.assertNotIn("BigMac",doc)
            self.assertNotIn("TrueNAS",doc)
            self.assertNotIn("apiKey",doc)
            self.assertNotIn("password",doc.lower())
            self.assertNotIn("https://",doc)
            self.assertNotIn("127.0.0.1",doc)  # endpoint not in prompt
            self.assertNotIn("VALUE=",doc)  # no hidden answer leaked
            self.assertEqual([m["role"] for m in p["messages"]],["system","user"])

    def test_unsupported_profiles_fail_closed(self):
        for profile in ("latest","private","", "large", "gpu", "medium-six"):
            with self.assertRaises(ValueError):
                make_profile(profile)

    def test_no_effectful_shell_or_ssh_tools(self):
        for profile in PROFILES:
            n=names(make_profile(profile))
            self.assertEqual(n[0],"read_file")
            self.assertTrue(set(n).issubset({"read_file","glob","list_directory"}))


if __name__=="__main__":
    unittest.main()
