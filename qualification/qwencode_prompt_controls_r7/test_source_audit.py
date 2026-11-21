"""Offline adversarial Qwen v0.28.3 prompt and tool-control source tests."""
import copy,json,os,sys,unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from source_audit import REQUIRED, source_check

PINS=json.loads((HERE/"source-pins.json").read_text())
RUNNER=(HERE/"run_lean_native.sh").read_text()
ROOT=HERE.parent.parent/"vendor/qwen"
FILES={path:(ROOT/path).read_bytes() for path in REQUIRED} if ROOT.is_dir() else {}


@unittest.skipUnless(FILES,"upstream exact checkout required; no mocked positive source")
class Positive(unittest.TestCase):
    def test_exact_full_prompt_vs_identity_and_tool_gate(self):
        report=source_check(PINS,FILES,RUNNER)
        self.assertEqual(report["result"],"PASS_SOURCE_IDENTITY_AND_INTENT")
        self.assertEqual(report["verified_blob_count"],4)
        self.assertEqual(report["override"],"FULL_BASE_SYSTEM_PROMPT_WHEN_QWEN_SYSTEM_MD_FILE")
        self.assertEqual(report["core_tools"],"EXPLICIT_NARROW_ALLOWLIST")
        self.assertEqual(report["signed_admission"],"NOT_GRANTED")


class Negative(unittest.TestCase):
    @unittest.skipUnless(FILES,"upstream checkout for negative source mutation")
    def test_mutated_source_digest_denied(self):
        altered=dict(FILES)
        altered["packages/core/src/core/prompts.ts"]+=b"// spoofed unsafe override\n"
        with self.assertRaises(ValueError):
            source_check(PINS,altered,RUNNER)

    @unittest.skipUnless(FILES,"upstream checkout for negative source mutation")
    def test_removed_exact_commit_denied(self):
        altered=copy.deepcopy(PINS)
        altered["commit"]="a"*40
        with self.assertRaises(ValueError):
            source_check(altered,FILES,RUNNER)

    @unittest.skipUnless(FILES,"upstream checkout for negative source mutation")
    def test_missing_core_gate_denied(self):
        with self.assertRaises(ValueError):
            source_check(PINS,FILES,RUNNER.replace("--core-tools read_file",""))

    @unittest.skipUnless(FILES,"upstream checkout for negative source mutation")
    def test_missing_full_system_override_denied(self):
        with self.assertRaises(ValueError):
            source_check(PINS,FILES,RUNNER.replace("export QWEN_SYSTEM_MD=",
                                                "export QWEN_SYSTEM_IDENTITY_MD="))

    @unittest.skipUnless(FILES,"upstream checkout for negative source mutation")
    def test_bridge_reenable_is_denied_for_small_model(self):
        altered=RUNNER.replace('"toolSearch":{"enabled":False}',
                               '"toolSearch":{"enabled":True}')
        with self.assertRaises(ValueError):
            source_check(PINS,FILES,altered)

    @unittest.skipUnless(FILES,"upstream checkout for negative source mutation")
    def test_floating_upstream_source_denied(self):
        altered=copy.deepcopy(PINS)
        altered["version"]="latest"
        with self.assertRaises(ValueError):
            source_check(altered,FILES,RUNNER)

if __name__=="__main__":unittest.main()
