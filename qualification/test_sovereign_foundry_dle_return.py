import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from qualification import sovereign_foundry_openworker as producer
from qualification.test_sovereign_foundry_openworker import FoundryTests

class DleReturnTests(unittest.TestCase):
    def admitted(self, root):
        out, digest = FoundryTests().fixture(root)
        names = ["manifest-digest", "embedded-build-receipt", "payload-hashes",
                 "offline-wheelhouse-install-no-resolve", "coworker-import-and-cli"]
        admission = {
            "schema_version":1, "record_type":"harness-artifact-admission",
            "artifact":{"ref":producer.IMAGE+"@"+digest, "digest":digest,
                        "build_receipt_digest":producer.digest_file(out/"payload"/"build-receipt.json")},
            "admission":{"state":"BUILD_ADMITTED",
                         "checks":[{"name":n,"result":"PASS"} for n in names]}}
        publication = {"state":"BUILD_ADMITTED","artifact_ref":producer.IMAGE+"@"+digest,
                       "manifest_digest":digest,"harness_realization":producer.realization_binding()}
        producer.atomic_json(out/"admission.json",admission)
        producer.atomic_json(out/"publication.json",publication)
        return out,digest

    def test_safe_verified_record(self):
        with tempfile.TemporaryDirectory() as td:
            out, digest = self.admitted(Path(td))
            data = producer.dle_record(out)
            self.assertEqual(data["manifest_digest"], digest)
            self.assertEqual(data["actor_task_qualification"], "NOT_PERFORMED")
            self.assertNotIn(str(out), producer.dle_body(data))

    def test_no_admission_no_report(self):
        with tempfile.TemporaryDirectory() as td:
            out,_ = FoundryTests().fixture(Path(td))
            with mock.patch.object(producer,"gh_api_json") as api:
                with self.assertRaises(ValueError):
                    producer.sync_dle(out)
                api.assert_not_called()

    def test_digest_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            out,_ = self.admitted(Path(td))
            path = out/"publication.json"
            record = json.loads(path.read_text())
            record["manifest_digest"]="sha256:"+"0"*64
            producer.atomic_json(path,record)
            with self.assertRaises(ValueError):
                producer.dle_record(out)

    def test_post_once(self):
        with tempfile.TemporaryDirectory() as td:
            out,digest = self.admitted(Path(td))
            body = producer.dle_body(producer.dle_record(out))
            posted={"body":body,"html_url":"https://github.com/SemperSupra/model-spelunker/issues/147#issuecomment-123"}
            with mock.patch.object(producer,"gh_api_json",side_effect=[[[]],posted]) as api:
                receipt=producer.sync_dle(out)
            self.assertEqual(receipt["state"],"RECORDED")
            self.assertEqual(receipt["manifest_digest"],digest)
            self.assertEqual(api.call_count,2)

    def test_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            out,_ = self.admitted(Path(td))
            body=producer.dle_body(producer.dle_record(out))
            with mock.patch.object(producer,"gh_api_json",return_value=[[{"body":body,"html_url":"https://github.com/example/issue/147"}]]) as api:
                result=producer.sync_dle(out)
            self.assertEqual(result["state"],"ALREADY_RECORDED")
            api.assert_called_once()

    def test_divergent_existing_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out,_ = self.admitted(Path(td))
            body=producer.dle_body(producer.dle_record(out))
            with mock.patch.object(producer,"gh_api_json",return_value=[[{"body":body+"CHANGED"}]]):
                with self.assertRaisesRegex(ValueError,"divergent"):
                    producer.sync_dle(out)

    def test_failed_admission_check_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out,_ = self.admitted(Path(td))
            path=out/"admission.json"
            data=json.loads(path.read_text())
            data["admission"]["checks"][0]["result"]="FAIL"
            producer.atomic_json(path,data)
            with self.assertRaisesRegex(ValueError,"unsuccessful"):
                producer.dle_record(out)

if __name__=="__main__":
    unittest.main()
