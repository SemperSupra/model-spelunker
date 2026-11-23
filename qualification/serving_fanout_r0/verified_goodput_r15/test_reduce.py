"""R15 RED/BLUE controls with self-generated synthetic receipt archives."""
import copy
import hashlib
import io
import json
import unittest
import zipfile
from reduce import (ADMISSION_REF,HARNESS_REF,MODEL_REF,TASK_DIGEST,SOURCE_SHA,
                    InvalidEvidence,reduce_bytes)

MODES={"serial":2,"parallel":2,"two_waves2":4,"burst4":4}
def make_fixture():
    archive={}
    summary={
        "evidence_class":"REAL_PUBLIC_CPU_SHARED_SERVER_CONFIGURED_AGENT_SCREEN",
        "backend":"ollama","model":"qwen3:1.7b","exact_model_artifact":"UNKNOWN_MAF_BINDING",
        "harness":"openworker","harness_artifact_ref":HARNESS_REF,
        "source_sha":SOURCE_SHA,"run_id":"45173592480",
        "shared_server_parallel_slots":2,"server_localhost_only":True,"phases":[]}
    for block in (1,2):
        for mode,count in MODES.items():
            tasks=[]
            for n in range(count):
                slot="agent"+chr(65+n)
                run_id="%s-%d-%s-%d"%(mode,block,slot,n)
                digest="sha256:"+hashlib.sha256(run_id.encode()).hexdigest()
                obs={"success":True,"termination_class":"semantic-success","verifier_exit_code":0,
                     "candidate_exit_code":0,"timed_out":False,"state_changed":True,
                     "wall_seconds":2.5,"tool_calls":1}
                raw={"schema_version":1,"run_id":run_id,"evidence_digest":digest,
                     "task":{"id":"text-repair-v0","task_class":"software.bounded-repair",
                             "package_digest":TASK_DIGEST,"source_commit":SOURCE_SHA},
                     "candidate":{"model":{"artifact_ref":MODEL_REF,"id":"qwen3:1.7b","provider":"ollama"},
                                  "harness":{"artifact_ref":HARNESS_REF,"admission_ref":ADMISSION_REF}},
                     "observation":obs}
                name="%s-block%d-%s-task.json"%(mode,block,slot)
                archive[name]=raw
                tasks.append({"workcell":slot,"task":"text-repair-v0","mode":mode,"block":block,
                              "run_id":run_id,"evidence_digest":digest,"verified_task_success":True,
                              "termination_class":"semantic-success","task_wall_seconds":2.5,
                              "client_wall_seconds":2.6,"verifier_exit_code":0,
                              "process_exit":0,"tool_calls":1})
            summary["phases"].append({"block":block,"mode":mode,
                                      "elapsed_wall_seconds":10.0,"verified_successes":count,
                                      "tasks":tasks})
    archive["shared-actor-summary.json"]=summary
    return archive

def pack(rows):
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name,row in sorted(rows.items()):
            z.writestr(name,json.dumps(row,sort_keys=True))
    data=mem.getvalue()
    return data,hashlib.sha256(data).hexdigest()

def evaluate(rows):
    data,digest=pack(rows)
    return reduce_bytes(data,expected_zip_sha=digest)

class VerifiedGoodputTests(unittest.TestCase):
    def test_recomputes_24_external_task_results(self):
        result=evaluate(make_fixture())
        self.assertEqual(result["total_validated_task_receipts"],24)
        self.assertEqual(result["total_independently_verified_successes"],24)
        self.assertEqual(len(result["cells"]),8)
        self.assertEqual(len(result["paired_comparisons"]),4)
        self.assertIsNone(result["observed_resource_reserve"])
        self.assertIsNone(result["prefill_decode_join"])
        self.assertEqual(result["promotion"],"HOLD_TASK_CLASS_LIMITED_NO_RESERVE_OR_SUSTAINED_SLO")

    def test_one_failed_task_must_not_count_as_goodput(self):
        a=make_fixture()
        name="serial-block1-agentA-task.json"
        raw=a[name]
        raw["observation"].update(success=False,termination_class="semantic-failure",
                                  verifier_exit_code=1,state_changed=False)
        row=a["shared-actor-summary.json"]["phases"][0]["tasks"][0]
        row.update(verified_task_success=False,termination_class="semantic-failure",
                   verifier_exit_code=1,process_exit=1)
        a["shared-actor-summary.json"]["phases"][0]["verified_successes"]=1
        result=evaluate(a)
        self.assertEqual(result["total_independently_verified_successes"],23)
        self.assertEqual(result["cells"][0]["policy"],"burst4")  # sorted by policy
        serial=next(c for c in result["cells"] if c["policy"]=="serial" and c["block"]==1)
        self.assertEqual(serial["verified_successes"],1)

    def test_rejects_claims_without_independent_validation(self):
        originals=make_fixture()
        mutants=[]
        a=copy.deepcopy(originals)
        a["shared-actor-summary.json"]["phases"][0]["verified_successes"]=999
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["shared-actor-summary.json"]["phases"][0]["tasks"][0]["verified_task_success"]=False
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["serial-block1-agentA-task.json"]["observation"]["verifier_exit_code"]=1
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["serial-block1-agentA-task.json"]["candidate"]["model"]["artifact_ref"]="ollama-sha256:other"
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["serial-block1-agentA-task.json"]["task"]["package_digest"]="sha256:wrong"
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["serial-block1-agentA-task.json"]["evidence_digest"]="sha256:"+"f"*64
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["serial-block1-agentA-task.json"]["run_id"]="forged"
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["serial-block1-agentA-task.json"]["observation"]["wall_seconds"]=float("nan")
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["serial-block1-agentA-task.json"]["observation"]["success"]=1
        mutants.append(a)
        a=copy.deepcopy(originals)
        a.pop("serial-block1-agentA-task.json")
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["unapproved-extra.json"]={}
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["serial-block1-agentA-task.json"]["schema_version"]=True
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["shared-actor-summary.json"]["source_sha"]="a"*40
        mutants.append(a)
        a=copy.deepcopy(originals)
        a["shared-actor-summary.json"]["phases"][1]["mode"]="serial"
        mutants.append(a)
        for i,case in enumerate(mutants):
            with self.subTest(mutant=i),self.assertRaises(InvalidEvidence):
                evaluate(case)

    def test_zip_digest_required(self):
        content,_=pack(make_fixture())
        with self.assertRaises(InvalidEvidence):
            reduce_bytes(content,expected_zip_sha="0"*64)

    def test_no_synthetic_to_real_promotion(self):
        obj=make_fixture()
        obj["shared-actor-summary.json"]["evidence_class"]="SYNTHETIC_SIMULATION_NOT_HARDWARE"
        with self.assertRaises(InvalidEvidence):
            evaluate(obj)

if __name__=="__main__":
    unittest.main()
