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

    def test_selected_model_diagnostic_has_no_fake_second_workcell(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fixture(Path(tmp),report.MODELS[0])
            result=report.reduce_folder(Path(tmp),123,"a"*40,(report.MODELS[0],))
            self.assertEqual(len(result["treatments"]),1)
            self.assertEqual(result["treatments"][0]["state"],"SEMANTIC_FAIL")
            self.assertNotIn(report.MODELS[1],report.body_of(result))

    def test_safe_tool_action_counts_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp))
            receipt=json.loads(path.read_text())
            receipt["observation"]["workload"].update({
                "tool_name_counts":{"read_file":2,"list_files":1,"write_file":1},
                "write_approvals_granted":1,
                "write_approvals_denied":0,
            })
            path.write_text(json.dumps(receipt))
            result=report.reduce_folder(Path(tmp),123,"a"*40)
            row=result["treatments"][0]
            self.assertEqual(row["observed_tool_name_counts"]["read_file"],2)
            self.assertEqual(row["write_approvals_granted"],1)
            self.assertNotIn("path",report.body_of(result))

    def test_iteration_budget_is_bound_into_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp))
            payload=json.loads(path.read_text())
            payload["observation"]["workload"]["configured_max_iterations"]=8
            path.write_text(json.dumps(payload))
            result=report.reduce_folder(Path(tmp),123,"a"*40,(report.MODELS[0],),8)
            self.assertEqual(result["treatments"][0]["max_iterations"],8)
            self.assertIn('"max_iterations": 8',report.body_of(result))
            with self.assertRaisesRegex(ValueError,"iteration budget"):
                report.reduce_folder(Path(tmp),123,"a"*40,(report.MODELS[0],),4)

    def test_zero_round_timeout_with_unknown_tools_is_censored_not_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            model="nvidia/nemotron-3-ultra-550b-a55b:free"
            path=self.fixture(Path(tmp),model)
            payload=json.loads(path.read_text())
            payload["task"]["id"]=report.TRANSFER_TASK
            payload["observation"].update({
                "timed_out":True,
                "candidate_exit_code":124,
                "tool_calls":None,
                "failure_class":"timeout",
                "failure_signals":["timeout","state-unchanged"],
                "engine_error_types":[],
                "workload":{"model_calls_started":1,"model_rounds":0,
                            "started_request_tool_schema_bytes_total":968,
                            "configured_max_iterations":8},
            })
            path.write_text(json.dumps(payload))
            result=report.reduce_folder(
                Path(tmp),38035293652,"a"*40,(model,),8,
                expected_task=report.TRANSFER_TASK
            )
            row=result["treatments"][0]
            self.assertEqual(row["state"],"TIMEOUT_CENSORED")
            self.assertIsNone(row["tool_calls"])
            self.assertEqual(row["completed_model_rounds"],0)
            self.assertEqual(result["task"],report.TRANSFER_TASK)
            self.assertNotIn('"state": "NO_RECEIPT"',report.body_of(result))

    def test_null_tools_must_not_mask_completed_task_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp))
            payload=json.loads(path.read_text())
            payload["observation"]["tool_calls"]=None
            payload["observation"]["workload"]["model_rounds"]=1
            path.write_text(json.dumps(payload))
            result=report.reduce_folder(Path(tmp),123,"a"*40)
            self.assertEqual(result["treatments"][0]["state"],"NO_RECEIPT")

    def test_null_tools_must_not_mask_claimed_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp))
            payload=json.loads(path.read_text())
            payload["observation"].update({
                "success":True,
                "verifier_exit_code":0,
                "tool_calls":None,
                "timed_out":True,
                "workload":{"model_rounds":0},
            })
            path.write_text(json.dumps(payload))
            result=report.reduce_folder(Path(tmp),123,"a"*40)
            self.assertEqual(result["treatments"][0]["state"],"NO_RECEIPT")

    def test_malformed_iteration_budget_cannot_be_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp))
            payload=json.loads(path.read_text())
            payload["observation"]["workload"]["configured_max_iterations"]="8"
            path.write_text(json.dumps(payload))
            result=report.reduce_folder(Path(tmp),123,"a"*40,(report.MODELS[0],),8)
            self.assertEqual(result["treatments"][0]["state"],"NO_RECEIPT")

    def test_one_large_free_model_is_distinct_from_legacy_cohort(self):
        with tempfile.TemporaryDirectory() as tmp:
            model="nvidia/nemotron-3-ultra-550b-a55b:free"
            path=self.fixture(Path(tmp),model)
            receipt=json.loads(path.read_text())
            receipt["observation"]["workload"]["configured_max_iterations"]=8
            path.write_text(json.dumps(receipt))
            only=report.reduce_folder(Path(tmp),123,"a"*40,(model,),8)
            self.assertEqual(len(only["treatments"]),1)
            self.assertEqual(only["treatments"][0]["model_id"],model)
            self.assertEqual(only["treatments"][0]["max_iterations"],8)
            with self.assertRaisesRegex(ValueError,"unselected model"):
                report.reduce_folder(Path(tmp),123,"a"*40)
            with self.assertRaisesRegex(ValueError,"iteration budget"):
                report.reduce_folder(Path(tmp),123,"a"*40,(model,),4)

    def test_independent_transfer_task_binds_identity_and_classifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            model="nvidia/nemotron-3-ultra-550b-a55b:free"
            path=self.fixture(folder,model)
            data=json.loads(path.read_text())
            data["task"]["id"]=report.TRANSFER_TASK
            data["observation"]["workload"]["configured_max_iterations"]=8
            path.write_text(json.dumps(data))
            result=report.reduce_folder(
                folder,123,"a"*40,(model,),8,expected_task=report.TRANSFER_TASK
            )
            self.assertEqual(result["task"],report.TRANSFER_TASK)
            self.assertEqual(result["treatments"][0]["state"],"SEMANTIC_FAIL")
            with self.assertRaisesRegex(ValueError,"unadmitted task"):
                report.reduce_folder(
                    folder,123,"a"*40,(model,),8,expected_task="unadmitted-task"
                )
            old=report.reduce_folder(folder,123,"a"*40,(model,),8)
            self.assertEqual(old["task"],report.TASK)
            self.assertEqual(old["treatments"][0]["state"],"NO_RECEIPT")
            self.assertIn('"task": "'+report.TRANSFER_TASK+'"',report.body_of(result))

    def test_transfer_absent_receipt_not_semantic_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=report.reduce_folder(
                Path(tmp),123,"a"*40,
                ("nvidia/nemotron-3-ultra-550b-a55b:free",),
                8,expected_task=report.TRANSFER_TASK,
            )
            self.assertEqual(result["task"],report.TRANSFER_TASK)
            self.assertEqual(result["treatments"][0]["state"],"NO_RECEIPT")

    def test_unauthorized_model_selection_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                report.reduce_folder(Path(tmp),123,"a"*40,("not-listed:free",))

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
