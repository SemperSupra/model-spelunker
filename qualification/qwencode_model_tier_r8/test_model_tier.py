"""Source-neutral R8 exact model-tier and effect boundary tests."""
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
RUN=(HERE/"run_4b_native.sh").read_text()


class Positive(unittest.TestCase):
    def test_exact_4b_instruct_and_read_file_only(self):
        for term in (
            "qwen3:4b-instruct",
            "0edcdef34593",
            "f361dc3992ec07e4ad429f4bb2d10d4663ba2c295f9a9a688c7d52f4ba650034",
            "export QWEN_SYSTEM_MD=",
            "export QWEN_WRITE_SYSTEM_MD=0",
            "--core-tools read_file",
            '--approval-mode default',
            '"toolSearch":{"enabled":False}',
            "sse_tool_delta_events",
            "hidden_fixture_oracle",
            "timeout 300",
            "trap cleanup EXIT"
        ):
            with self.subTest(signal=term[:30]):
                self.assertIn(term,RUN)
        self.assertNotIn("--approval-mode yolo",RUN)
        self.assertNotIn("qwen3:1.7b",RUN)

    def test_only_exempt_task_stop_extra_tool_is_recorded(self):
        self.assertIn('"read_file","task_stop"',RUN)
        self.assertIn('v.get("tools_count",100)==2',RUN)
        self.assertNotIn("git push",RUN)


class Negative(unittest.TestCase):
    def test_deny_public_private_identifiers_and_secret_material(self):
        for term in ("BigMac","TrueNAS","mark-e-deyoung/infrastructure-as-code-private",
                     "ssh -","curl -sSf |","PRIVATE_KEY","GITHUB_TOKEN",
                     "OpenRouter", "sk-"):
            with self.subTest(term=term):
                self.assertNotIn(term,RUN)
    def test_no_ambient_live_host_or_public_private_credential(self):
        self.assertIn('export OLLAMA_HOST=127.0.0.1:11434',RUN)
        self.assertIn('private_host_or_model',RUN)
        self.assertIn('source_class',RUN)

if __name__=="__main__":
    unittest.main()
