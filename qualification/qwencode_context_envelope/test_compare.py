import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from compare import prepare, TARGET_CHARS, TARGET_REQUEST_BYTES

class ContextPositive(unittest.TestCase):
    def test_disjoint_shape_and_single_changed_dimension(self):
        small=prepare("small")
        large=prepare("large")
        assert small["model"]==large["model"]=="qwen3:1.7b"
        assert small["messages"][1]==large["messages"][1]
        assert small["reasoning_effort"]==large["reasoning_effort"]=="none"
        assert small["stream"] and large["stream"]
        assert len(small["tools"])==1 and len(large["tools"])==3
        assert len(large["messages"][0]["content"])==TARGET_CHARS
        assert len(json.dumps(large,separators=(",",":")).encode())>=TARGET_REQUEST_BYTES

class ContextNegatives(unittest.TestCase):
    def test_no_privileged_tool_or_private_content(self):
        for profile in ("small","large"):
            p=prepare(profile)
            assert all(t["function"]["name"] not in ("shell_exec","sudo","git_push") for t in p["tools"])
            s=json.dumps(p)
            for term in ("BigMac","TrueNAS","apiKey","private-repo","password","ssh"):
                assert term not in s
            assert p["messages"][1]["content"].find("VALUE=")==-1
            assert p["model"]=="qwen3:1.7b"
    def test_bad_profiles_fail_closed(self):
        for profile in ("latest", "private", "gpu", "", "large-context-prod"):
            with self.assertRaises(AssertionError):
                prepare(profile)

if __name__=="__main__":
    unittest.main()
