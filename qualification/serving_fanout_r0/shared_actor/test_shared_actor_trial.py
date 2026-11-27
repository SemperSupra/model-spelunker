import os
import tempfile
import unittest
from pathlib import Path
import shared_actor_trial as a

def receipt(task="text-repair-v0",success=True):
    return {
      "task":{"id":task,"package_digest":a.TASK_PACKAGE_DIGEST},"candidate":{
        "harness":{"name":"openworker","artifact_ref":a.HARNESS_REF,
                   "admission_ref":a.ADMISSION_REF},
        "model":{"id":"qwen3:1.7b","provider":"ollama","artifact_ref":a.PUBLIC_MODEL_ARTIFACT}},
      "evidence_digest":"sha256:"+("b"*64),
      "run_id":"synthetic-test-id",
      "observation":{"success":success,
          "termination_class":"semantic-success" if success else "semantic-failure",
          "failure_class":None if success else "false-completion",
          "wall_seconds":1.5,"verifier_exit_code":0 if success else 1,"candidate_exit_code":0 if success else 1,"timed_out":False,
          "tool_calls":1}
    }

class ContractTests(unittest.TestCase):
    def test_positive_and_negative_task_observations(self):
        self.assertTrue(a.check_receipt(receipt(), "text-repair-v0",0,"qwen3:1.7b")["verified_task_success"])
        self.assertFalse(a.check_receipt(receipt(success=False),"text-repair-v0",1,"qwen3:1.7b")["verified_task_success"])
    def test_mismatched_verification_and_identity_fail_closed(self):
        p=receipt()
        for corrupted in (
          ({"task":{"id":"other"}},"task"),
          ({"candidate":{"harness":{"artifact_ref":"wrong"},"model":{"id":"qwen3:1.7b","provider":"ollama"}}},"artifact"),
          ({"candidate":{"harness":{"artifact_ref":a.HARNESS_REF,"admission_ref":a.ADMISSION_REF},"model":{"id":"other","provider":"ollama"}}},"model"),
          ({"evidence_digest":""},"evidence")):
            payload=dict(p);payload.update(corrupted[0])
            with self.assertRaises(ValueError,msg=corrupted[1]):
                a.check_receipt(payload,"text-repair-v0",0,"qwen3:1.7b")
        with self.assertRaises(ValueError):
            a.check_receipt(receipt(success=True),"text-repair-v0",1,"qwen3:1.7b")
    def test_bounded_duplicate_task_workcells(self):
        self.assertEqual(len(a.TASKS),2)
        self.assertEqual([x[1] for x in a.TASKS],["text-repair-v0","text-repair-v0"])
        self.assertEqual(len(set(x[0] for x in a.TASKS)),2)
        self.assertEqual(len(a.HARNESS_DIGEST),64)
        self.assertEqual(len(a.FOUR_TASKS),4)
        self.assertEqual(len(set(slot for slot,task in a.FOUR_TASKS)),4)
        self.assertTrue(all(task=="text-repair-v0" for slot,task in a.FOUR_TASKS))

    def test_runner_command_is_existing_task_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous=os.environ.get("CANDIDATE_META")
            os.environ["CANDIDATE_META"]=tmp+"/candidate.json"
            try:
                v=a.cmd("text-repair-v0",Path(tmp)/"receipt.json",Path(tmp)/"diagnostics.json",Path(tmp))
                self.assertIn("qualification/run_task.py"," ".join(v))
                self.assertIn("--task-commit",v)
                self.assertIn("--pass-env",v)
                self.assertIn("text-repair-v0"," ".join(v))
            finally:
                if previous is None:os.environ.pop("CANDIDATE_META",None)
                else:os.environ["CANDIDATE_META"]=previous
    def test_forged_verifier_and_representation_rejected(self):
        import copy
        original=receipt()
        mutations=[
           ("model-drift",lambda p:p["candidate"]["model"].update(artifact_ref="ollama-sha256:"+"f"*64)),
           ("fixture-drift",lambda p:p["task"].update(package_digest="sha256:"+"f"*64)),
           ("verifier-forgery",lambda p:p["observation"].update(verifier_exit_code=1)),
           ("candidate-forgery",lambda p:p["observation"].update(candidate_exit_code=1)),
           ("timeout-forgery",lambda p:p["observation"].update(timed_out=True)),
           ("missing-run",lambda p:p.update(run_id=None)),
           ("bad-digest",lambda p:p.update(evidence_digest="sha256:bad")),
        ]
        for label,change in mutations:
            p=copy.deepcopy(original)
            change(p)
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    a.check_receipt(p,"text-repair-v0",0,"qwen3:1.7b")
if __name__=="__main__":unittest.main()
