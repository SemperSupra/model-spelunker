"""Offline deterministic source-gate tests for Model Spelunker Heretic #189."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qualification"))
from heretic_pair_preflight import (MAX_METADATA_BYTES, MAX_TEMPLATE_BYTES, PAIRS, main,
                                    pair_report, public_api_metadata, public_chat_template,
                                    read_metadata_json,
                                    read_template_bytes)

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

    def test_standalone_template_requires_pinned_bytes(self):
        self.base["siblings"].append({"rfilename": "chat_template.jinja"})
        self.modified["siblings"].append({"rfilename": "chat_template.jinja"})
        report = self.report()
        self.assertEqual(report["source_gate"], "HOLD")
        self.assertIn("PINNED_TEMPLATE_FILE_NOT_VERIFIED", report["base"]["holds"])
        self.assertIn("PINNED_TEMPLATE_FILE_NOT_VERIFIED", report["modified"]["holds"])

    def test_same_standalone_templates_can_pass_metadata_gate_only(self):
        self.base["siblings"].append({"rfilename": "chat_template.jinja"})
        self.modified["siblings"].append({"rfilename": "chat_template.jinja"})
        report = pair_report("qwen-4b-instruct", self.base, self.modified, SHA_A, SHA_B,
                             base_template="verified", modified_template="verified")
        self.assertEqual(report["source_gate"], "METADATA_READY_ONLY")
        self.assertEqual(report["base"]["chat_template_source"], "pinned_file")
        self.assertEqual(report["actor_qualification"], "UNKNOWN_NOT_EXECUTED")

    def test_different_standalone_templates_confounded(self):
        self.base["siblings"].append({"rfilename": "chat_template.jinja"})
        self.modified["siblings"].append({"rfilename": "chat_template.jinja"})
        report = pair_report("qwen-4b-instruct", self.base, self.modified, SHA_A, SHA_B,
                             base_template="verified", modified_template="different")
        self.assertIn("CHAT_TEMPLATE_DIFFERS_REQUIRES_EXPERIMENT_CONTROL", report["cross_checks"])

    def test_unexpected_offline_template_file_holds(self):
        report = pair_report("qwen-4b-instruct", self.base, self.modified, SHA_A, SHA_B,
                             base_template="out-of-band")
        self.assertIn("UNEXPECTED_TEMPLATE_FILE", report["base"]["holds"])

    def test_standalone_template_size_and_encoding_guards(self):
        with self.assertRaisesRegex(ValueError, "exceeds bound"):
            read_template_bytes(b"x" * (MAX_TEMPLATE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "empty chat template"):
            read_template_bytes(b"   ")
        with self.assertRaises(UnicodeDecodeError):
            read_template_bytes(b"\xff")

    def test_offline_cli_pins_both_template_files(self):
        self.base["siblings"].append({"rfilename": "chat_template.jinja"})
        self.modified["siblings"].append({"rfilename": "chat_template.jinja"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "base.json").write_text(json.dumps(self.base), encoding="utf-8")
            (root / "mod.json").write_text(json.dumps(self.modified), encoding="utf-8")
            (root / "base.jinja").write_text("template", encoding="utf-8")
            (root / "mod.jinja").write_text("template", encoding="utf-8")
            rc = main(["--pair", "qwen-4b-instruct",
                       "--base-json", str(root / "base.json"),
                       "--modified-json", str(root / "mod.json"),
                       "--base-template-file", str(root / "base.jinja"),
                       "--modified-template-file", str(root / "mod.jinja"),
                       "--base-sha", SHA_A, "--modified-sha", SHA_B,
                       "--output", str(root / "report.json")])
            self.assertEqual(rc, 0)
            receipt = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["base"]["chat_template_source"], "pinned_file")
            self.assertEqual(receipt["runtime_gate"].startswith("HOLD"), True)

    def test_live_template_path_requires_known_model_and_exact_sha(self):
        with self.assertRaisesRegex(ValueError, "unknown model"):
            public_chat_template("attacker/unknown", SHA_A)
        with self.assertRaisesRegex(ValueError, "unpinned"):
            public_chat_template("Qwen/Qwen3-4B-Instruct-2507", "main")

    def test_pinned_hf_metadata_request_uses_exact_revision(self):
        model_id = "Qwen/Qwen3-4B-Instruct-2507"
        expected_url = ("https://huggingface.co/api/models/" + model_id +
                        "/revision/" + SHA_A)
        metadata = fixture(model_id, SHA_A)
        seen = []
        class Response:
            url = expected_url
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def read(self, n):
                self.limit = n
                return json.dumps(metadata).encode("utf-8")
        def fake_urlopen(req, timeout):
            seen.append((req.full_url, timeout))
            return Response()
        with patch("heretic_pair_preflight.urllib.request.urlopen",
                   side_effect=fake_urlopen):
            received = public_api_metadata(model_id, SHA_A)
        self.assertEqual(seen, [(expected_url, 12)])
        self.assertEqual(received["sha"], SHA_A)

    def test_hf_metadata_requires_pinned_known_source(self):
        with self.assertRaisesRegex(ValueError, "unpinned metadata"):
            public_api_metadata("Qwen/Qwen3-4B-Instruct-2507", "main")
        with self.assertRaisesRegex(ValueError, "unknown model"):
            public_api_metadata("untrusted/model", SHA_A)

    def test_hf_metadata_redirect_denied(self):
        model_id = "Qwen/Qwen3-4B-Instruct-2507"
        class Response:
            url = "https://other-host.example/api/models"
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def read(self, n):
                return b"{}"
        with patch("heretic_pair_preflight.urllib.request.urlopen",
                   return_value=Response()):
            with self.assertRaisesRegex(ValueError, "metadata redirect denied"):
                public_api_metadata(model_id, SHA_A)

    def test_online_mode_cannot_use_floating_revisions(self):
        with self.assertRaises(SystemExit):
            main(["--pair", "qwen-4b-instruct", "--fetch-public-metadata"])

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
