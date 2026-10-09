#!/usr/bin/env python3
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from qualification import report_openrouter_free_interviews as report


class Tests(unittest.TestCase):
    def fixture(self, folder, model=report.MODELS[0]):
        receipt={
            "candidate":{
                "model":{"id":model,"provider":"openrouter"},
                "harness":{"artifact_ref":report.ARTIFACT},
            },
            "task":{"id":report.TASK},
            "evidence_digest":"sha256:"+"a"*64,
            "observation":{
                "success":False, "verifier_exit_code":1,
                "tool_calls":0,"candidate_exit_code":0,
                "failure_class":"false-completion",
                "workload":{"model_rounds":1,"provider_finish_reason_counts":{"stop":1}},
            },
        }
        path=folder/("receipt-"+model.replace("/","_")+".json")
        path.write_text(json.dumps(receipt))
        return path

    def test_no_receipt_is_not_model_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=report.reduce_folder(Path(tmp),123,"a"*40)
            self.assertTrue(all(row["state"]=="NO_RECEIPT" for row in result["treatments"]))
            self.assertNotIn('"state": "SEMANTIC_FAIL"',report.body_of(result))

    def test_valid_verifier_fail_is_semantic(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fixture(Path(tmp))
            result=report.reduce_folder(Path(tmp),123,"a"*40)
            rows=result["treatments"]
            self.assertEqual(rows[0]["state"],"SEMANTIC_FAIL")
            self.assertEqual(rows[0]["provider_finish_reason_counts"],{"stop":1})
            self.assertEqual(rows[1]["state"],"NO_RECEIPT")
            self.assertNotIn(tmp,report.body_of(result))

    def test_rate_limit_is_censored_not_semantic_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp),report.MODELS[1])
            receipt=json.loads(path.read_text())
            receipt["observation"]["engine_error_types"]=["RateLimitError"]
            receipt["observation"]["failure_class"]="candidate-error-event"
            receipt["observation"]["failure_signals"]=["engine-error-event","state-unchanged"]
            receipt["observation"]["workload"]={"model_calls_started":1,"model_rounds":0}
            path.write_text(json.dumps(receipt))
            row=report.reduce_folder(Path(tmp),123,"a"*40)["treatments"][1]
            self.assertEqual(row["state"],"PROVIDER_RATE_LIMIT_CENSORED")
            self.assertEqual(row["completed_model_rounds"],0)
            self.assertEqual(row["observed_engine_error_types"],["RateLimitError"])
            self.assertEqual(row["external_verifier_exit_code"],1)
            self.assertNotEqual(row["state"],"SEMANTIC_FAIL")

    def test_empty_rounds_without_error_are_censored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp))
            receipt=json.loads(path.read_text())
            receipt["observation"]["workload"]={"model_rounds":0}
            path.write_text(json.dumps(receipt))
            row=report.reduce_folder(Path(tmp),123,"a"*40)["treatments"][0]
            self.assertEqual(row["state"],"NO_MODEL_COMPLETION_CENSORED")

    def test_identity_drift_rejected_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp))
            document=json.loads(path.read_text())
            document["candidate"]["harness"]["artifact_ref"]="ghcr.io/other"
            path.write_text(json.dumps(document))
            result=report.reduce_folder(Path(tmp),123,"a"*40)
            self.assertEqual(result["treatments"][0]["state"],"NO_RECEIPT")

    def test_reject_conflicting_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp))
            document=json.loads(path.read_text())
            document["observation"]["success"]=True
            path.write_text(json.dumps(document))
            result=report.reduce_folder(Path(tmp),123,"a"*40)
            self.assertEqual(result["treatments"][0]["state"],"NO_RECEIPT")

    def test_dle_posts_identical_payload_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            body=report.body_of(report.reduce_folder(Path(tmp),123,"a"*40))
        url="https://github.com/SemperSupra/model-spelunker/issues/139#issuecomment-456"
        with mock.patch.object(report,"gh_api",side_effect=[[[]],{"body":body,"html_url":url}]) as api:
            recorded=report.post_once(body)
            self.assertEqual(recorded["state"],"RECORDED")
            self.assertEqual(api.call_count,2)
        with mock.patch.object(report,"gh_api",return_value=[[{"body":body,"html_url":url}]]) as api:
            again=report.post_once(body)
            self.assertEqual(again["state"],"ALREADY_RECORDED")
            api.assert_called_once()

    def test_dle_divergent_duplicate_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            body=report.body_of(report.reduce_folder(Path(tmp),123,"a"*40))
        with mock.patch.object(report,"gh_api",return_value=[[{"body":body+"tampered"}]]):
            with self.assertRaisesRegex(ValueError,"conflicts"):
                report.post_once(body)


if __name__=="__main__":
    unittest.main()
