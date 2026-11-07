"""Offline deterministic source-gate tests for Model Spelunker Heretic #189."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qualification"))
from heretic_pair_preflight import MAX_METADATA_BYTES, PAIRS, main, pair_report, read_metadata_json

SHA_A = "a" * 40
SHA_B = "b" * 40

def fixture(model_id, revision, model_type="qwen3", license_name="apache-2.0", template="shared"):
    return {
        "id": model_id, "sha": revision, "private": False, "gated": False, "disabled": False,
        "cardData": {"license": license_name, "license_name": license_name},
        "config": {"model_type": model_type, "tokenizer_config": {"chat_template": template}},
        "siblings": [{"rfilename": name} for name in
                     ("config.json", "tokenizer_config.json", "model-00001.safetensors")],
    }

class HereticPairSourcePreflightTests(unittest.TestCase):
    def setUp(self):
        base_id, modified_id, _ = PAIRS["qwen-4b-instruct"]
        self.base = fixture(base_id, SHA_A)
        self.modified = fixture(modified_id, SHA_B)

    def report(self, base_sha=SHA_A, modified_sha=SHA_B):
        return pair_report("qwen-4b-instruct", self.base, self.modified, base_sha, modified_sha)

    def test_nominal_is_metadata_only_never_actor_success(self):
        report = self.report()
        self.assertEqual(report["source_gate"], "METADATA_READY_ONLY")
        self.assertEqual(report["actor_qualification"], "UNKNOWN_NOT_EXECUTED")
        self.assertEqual(report["inference_calls"], 0)
        self.assertTrue(report["runtime_gate"].startswith("HOLD_"))

    def test_unpinned_revisions_hold(self):
        report = self.report(None, None)
        self.assertIn("REVISION_LOCK_NOT_SUPPLIED", report["base"]["holds"])
        self.assertEqual(report["source_gate"], "HOLD")

    def test_revision_drift_hold(self):
        self.assertIn("REVISION_DRIFT", self.report(SHA_B, SHA_B)["base"]["holds"])

    def test_unrelated_repository_id_hold(self):
        self.modified["id"] = "attacker/not-the-heretic-model"
        self.assertIn("MODEL_ID_MISMATCH", self.report()["modified"]["holds"])

    def test_non_public_or_gated_hold(self):
        for field, value in (("private", True), ("gated", True), ("disabled", True), ("gated", None)):
            with self.subTest(field=field, value=value):
                self.modified[field] = value
                self.assertIn("MODEL_NOT_PUBLIC_UNGATED_ENABLED", self.report()["modified"]["holds"])
                self.modified[field] = False

    def test_license_mismatch_hold(self):
        self.modified["cardData"]["license_name"] = "wrong"
        self.assertIn("LICENSE_UNVERIFIED_OR_MISMATCH", self.report()["modified"]["holds"])

    def test_architecture_confounded(self):
        self.modified["config"]["model_type"] = "other"
        self.assertIn("MODEL_ARCHITECTURE_NOT_MATCHED", self.report()["cross_checks"])

    def test_chat_template_confounded(self):
        self.modified["config"]["tokenizer_config"]["chat_template"] = "different"
        self.assertIn("CHAT_TEMPLATE_DIFFERS_REQUIRES_EXPERIMENT_CONTROL", self.report()["cross_checks"])

    def test_chat_template_unverified(self):
        self.modified["config"]["tokenizer_config"] = {}
        self.assertIn("CHAT_TEMPLATE_UNVERIFIED", self.report()["modified"]["holds"])

    def test_missing_model_files(self):
        self.modified["siblings"] = []
        self.assertIn("SAFETENSORS_WEIGHTS_MISSING", self.report()["modified"]["holds"])
        self.assertIn("MODEL_CONFIG_OR_TOKENIZER_MISSING", self.report()["modified"]["holds"])

    def test_cli_offline_snapshot_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "base.json").write_text(json.dumps(self.base), encoding="utf-8")
            (root / "mod.json").write_text(json.dumps(self.modified), encoding="utf-8")
            rc = main(["--pair", "qwen-4b-instruct",
                       "--base-json", str(root / "base.json"),
                       "--modified-json", str(root / "mod.json"),
                       "--base-sha", SHA_A, "--modified-sha", SHA_B,
                       "--output", str(root / "out.json")])
            self.assertEqual(rc, 0)
            report = json.loads((root / "out.json").read_text(encoding="utf-8"))
            self.assertEqual(report["actor_qualification"], "UNKNOWN_NOT_EXECUTED")

    def test_cli_missing_snapshot_fails_closed(self):
        with self.assertRaises(SystemExit):
            main(["--pair", "qwen-4b-instruct", "--base-json", "/tmp/only-one.json"])

    def test_duplicate_json_keys_denied(self):
        with self.assertRaisesRegex(ValueError, "duplicate metadata"):
            read_metadata_json(b'{"id":"first","id":"second"}')

    def test_nonfinite_json_value_denied(self):
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            read_metadata_json(b'{"downloads":NaN}')

    def test_oversized_metadata_denied_before_parse(self):
        with self.assertRaisesRegex(ValueError, "exceeds bound"):
            read_metadata_json(b" " * (MAX_METADATA_BYTES + 1))

    def test_truncated_metadata_denied(self):
        with self.assertRaises(ValueError):
            read_metadata_json(b'{"id":"incomplete"')

    def test_lfm_is_licensed_separately(self):
        base_id, modified_id, license_name = PAIRS["lfm-2.6b"]
        self.assertEqual(license_name, "lfm1.0")
        result = pair_report("lfm-2.6b",
                             fixture(base_id, SHA_A, "lfm2", "lfm1.0"),
                             fixture(modified_id, SHA_B, "lfm2", "lfm1.0"),
                             SHA_A, SHA_B)
        self.assertEqual(result["source_gate"], "METADATA_READY_ONLY")

if __name__ == "__main__":
    unittest.main()
