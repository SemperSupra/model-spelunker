import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reduce import validate

BASE=json.loads((Path(__file__).parent/"public-sources.json").read_text())


class ProvenancePositive(unittest.TestCase):
    def test_reuse_is_inherited_not_qwen_installation(self):
        r=validate(copy.deepcopy(BASE))
        self.assertEqual(r["source_evidence_count"],3)
        self.assertEqual(r["boot_substrate"],"REUSABLE_OTHER_WORKSET")
        self.assertEqual(r["psdirect_substrate"],
                         "REUSABLE_OTHER_WORKSET_WITH_RECOVERED_GATE")
        self.assertEqual(r["qwen_in_guest"],"NOT_TESTED")
        self.assertEqual(r["sovereign_site"],"NOT_ADMITTED")
        self.assertIs(r["dispatch_authorized"],False)

    def test_exact_source_provenance_not_an_execution_plan(self):
        r=validate(copy.deepcopy(BASE))
        self.assertEqual(r["source_class"],"PUBLIC_SOURCE")
        self.assertEqual(r["private_actions_minutes"],0)
        self.assertEqual(BASE["evidence"][2]["original_gate"],"FAIL_FILENAME_ONLY")
        self.assertEqual(BASE["adoption"]["status"],"SOURCE_INPUT_READY_NOT_EXECUTION_ADMITTED")


class ProvenanceRedteam(unittest.TestCase):
    def bad(self, edit):
        d=copy.deepcopy(BASE)
        edit(d)
        with self.assertRaises(ValueError):
            validate(d)

    def test_false_qwen_guest_pass(self):
        self.bad(lambda d: d["boundaries"].__setitem__("qwen_guest_installed","PASS"))
    def test_false_tool_call(self):
        self.bad(lambda d: d["boundaries"].__setitem__("qwen_guest_tool_call","PASS"))
    def test_false_model_call(self):
        self.bad(lambda d: d["boundaries"].__setitem__("qwen_guest_model_inference","PASS"))
    def test_false_private_admission(self):
        self.bad(lambda d: d["boundaries"].__setitem__("real_private_host_admission","READY"))
    def test_false_credential_authority(self):
        self.bad(lambda d: d["boundaries"].__setitem__("production_credential_projection","AUTHORIZED"))
    def test_missing_recovered_verifier(self):
        self.bad(lambda d: d["evidence"][2].__setitem__("independent_gate","FAIL"))
    def test_original_gate_failure_erased(self):
        self.bad(lambda d: d["evidence"][2].__setitem__("original_gate","PASS"))
    def test_unapproved_inherited_dispatch(self):
        self.bad(lambda d: d["boundaries"].__setitem__("public_workflow_can_reuse_parent_without_grant",True))
    def test_private_projection(self):
        self.bad(lambda d: d["boundaries"].__setitem__("no_private_source_in_public_runner",False))
    def test_bad_image_hash(self):
        self.bad(lambda d: d["guest_image"].__setitem__("sha256","floating-latest"))
    def test_bad_sha(self):
        self.bad(lambda d: d["evidence"][1].__setitem__("source_sha","main"))
    def test_duplicate_run(self):
        self.bad(lambda d: d["evidence"][2].__setitem__(
            "recovered_run_id",d["evidence"][2]["run_id"]))
    def test_guest_boot_cannot_be_witnessed_from_h0_alone(self):
        self.bad(lambda d: d["evidence"][1].__setitem__("claim","SUPPORTED"))
    def test_unsigned_provenance_source_cannot_grant_execution(self):
        self.bad(lambda d: d["adoption"].__setitem__("status","READY_APPLY"))

if __name__=="__main__":
    unittest.main()
