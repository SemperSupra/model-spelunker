"""Offline independent counterexample tests. No network, credentials or effects."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify import ROOT,validate_ledger,verify,verify_one,live_get
HERE=Path(__file__).resolve().parent
LEDGER=json.loads((HERE.parent/"qwen_batches/workset.public.json").read_text())
RULES=json.loads((HERE/"reviewed-job-oracles.json").read_text())


def responses(plan,rules):
    lookup={}
    targets=validate_ledger(plan,rules)
    for name,t in targets.items():
        url=ROOT+str(t["run_id"])
        lookup[url]={
            "head_sha":t["source_sha"],
            "status":"completed",
            "conclusion":t["expected_run_conclusion"],
            "name":"Synthetic test-only CI evidence",
            "repository":{"full_name":"SemperSupra/model-spelunker"}
        }
        jobs=[{"name":n,"status":"completed","conclusion":v}
              for n,v in t["jobs"].items()]
        lookup[url+"/jobs?per_page=100"]={"total_count":len(jobs),"jobs":jobs}
    return lookup


class Positive(unittest.TestCase):
    def test_all_six_source_bound_remote_status_receipts(self):
        response=responses(LEDGER,RULES)
        out=verify(LEDGER,RULES,lambda url:response[url])
        self.assertEqual(out["packets"],6)
        self.assertEqual(out["external_job_assertions"],14)
        self.assertEqual(out["state"],"PASS_GHA_SOURCE_AND_JOB_STATUS")
        self.assertFalse(out["admission_authorized"])
        self.assertFalse(out["semantic_model_claims_verified"])

    def test_failures_remain_failures(self):
        out=verify(LEDGER,RULES,lambda u:responses(LEDGER,RULES)[u])
        failed=[r for r in out["results"] if r["workflow_conclusion"]=="failure"]
        self.assertEqual({r["packet"] for r in failed},
                         {"B07-REAL-QWEN-HARNESS","B08-CONTEXT-CROSSOVER"})


class Negative(unittest.TestCase):
    def mutant_ledger(self,change):
        d=copy.deepcopy(LEDGER)
        change(d)
        with self.assertRaises((ValueError,TypeError)):
            validate_ledger(d,RULES)

    def mutant_remote(self,change):
        response=responses(LEDGER,RULES)
        change(response)
        with self.assertRaises((ValueError,TypeError,KeyError)):
            verify(LEDGER,RULES,lambda u:response[u])

    def test_wrong_sha(self):
        self.mutant_ledger(lambda d:d["tasks"][0].__setitem__("source_sha","0"*40))

    def test_same_sha_but_forged_run(self):
        self.mutant_ledger(lambda d:d["tasks"][0]["evidence"].__setitem__(
            "run_url","https://github.com/SemperSupra/model-spelunker/actions/runs/99999999"))

    def test_private_github_leak_denied(self):
        self.mutant_ledger(lambda d:d["tasks"][0].__setitem__(
            "repo","mark-e-deyoung/infrastructure-as-code-private"))

    def test_failure_promoted(self):
        self.mutant_ledger(lambda d:d["tasks"][6].__setitem__("state","DONE_VERIFIED"))

    def test_self_claimed_false_failure(self):
        self.mutant_ledger(lambda d:d["tasks"][7]["evidence"].__setitem__(
            "independent_oracle","PASS"))

    def test_missing_external_job(self):
        u=ROOT+"44875274568/jobs?per_page=100"
        self.mutant_remote(lambda d:d[u]["jobs"].pop())

    def test_wrong_external_job_conclusion(self):
        u=ROOT+"44875274568/jobs?per_page=100"
        self.mutant_remote(lambda d:d[u]["jobs"][0].__setitem__("conclusion","failure"))

    def test_wrong_run_source(self):
        u=ROOT+"44875470102"
        self.mutant_remote(lambda d:d[u].__setitem__("head_sha","e"*40))

    def test_failed_run_claims_success(self):
        u=ROOT+"44876312124"
        self.mutant_remote(lambda d:d[u].__setitem__("conclusion","success"))

    def test_nonterminal_status(self):
        u=ROOT+"44875976976"
        self.mutant_remote(lambda d:d[u].__setitem__("status","in_progress"))

    def test_page_incomplete(self):
        u=ROOT+"44876698668/jobs?per_page=100"
        self.mutant_remote(lambda d:d[u].__setitem__("total_count",999))

    def test_missing_repo_from_remote(self):
        u=ROOT+"44875793329"
        self.mutant_remote(lambda d:d[u]["repository"].__setitem__(
            "full_name","bad/unsafe"))

    def test_duplicate_job_fails(self):
        u=ROOT+"44875793329/jobs?per_page=100"
        def duplicate(d):
            d[u]["jobs"].append(d[u]["jobs"][0])
            d[u]["total_count"]+=1
        self.mutant_remote(duplicate)

    def test_restricted_public_api_url(self):
        with self.assertRaises(ValueError):
            live_get("https://api.github.com/repos/another/private/contents/.env")
        with self.assertRaises(ValueError):
            live_get(ROOT+"44875274568?secret=1")
        with self.assertRaises(ValueError):
            live_get(ROOT+"44875274568/../../contents")

    def test_no_unbounded_issue_or_conclusion(self):
        d=copy.deepcopy(RULES)
        d["rules"]["B01-WIRE-DIAG"]["jobs"]={"unexpected":"queued"}
        with self.assertRaises(ValueError):
            validate_ledger(LEDGER,d)


if __name__=="__main__":
    unittest.main()
