"""Ensure the bridge does not become a second wave planner/authority."""
import copy
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from bridge import convert

FIX=json.loads((HERE/"synthetic-ready.json").read_text())
LEDGER=json.loads((HERE.parent/"qwen_batches/workset.public.json").read_text())


class Positive(unittest.TestCase):
    def test_two_public_cards_are_emitted_for_existing_go_contract(self):
        converted=convert(copy.deepcopy(FIX))
        self.assertEqual(converted["schema"],"batch-wave/v1")
        self.assertEqual(len(converted["cards"]),2)
        ids=[x["id"] for x in converted["cards"]]
        self.assertEqual(ids,["b09-synthetic-one","b10-source-two"])
        self.assertEqual(len(set(x["branch"] for x in converted["cards"])),2)
        self.assertEqual(len(set(x["resources"][0] for x in converted["cards"])),2)
        for card in converted["cards"]:
            self.assertEqual(card["venue"],"public-gha")
            self.assertEqual(card["data_class"],"public-safe")
            self.assertEqual(card["depends"],[])
            self.assertLessEqual(len(card["steps"]),6)
            self.assertIn("qualification/receipts/",card["writes"][-1])
            self.assertNotIn("admission",card)

    def test_live_real_ledger_has_zero_eligible_public_jobs(self):
        converted=convert(copy.deepcopy(LEDGER))
        self.assertEqual(converted["state"],"NO_READY_PUBLIC_TASKS")
        self.assertFalse(converted["dispatch_authorized"])
        self.assertEqual(converted["cards"],0)


class Negative(unittest.TestCase):
    def bad(self,mutation):
        doc=copy.deepcopy(FIX)
        mutation(doc)
        with self.assertRaises((ValueError,KeyError,TypeError,StopIteration)):
            convert(doc)

    def test_over_two_ready_refuses_implicit_selection(self):
        def add(d):
            x=copy.deepcopy(d["tasks"][0])
            x["id"]="B11-THIRD-PACKET"
            x["scope"]=["qualification/synthetic_fixture_three/"]
            d["tasks"].append(x)
        self.bad(add)

    def test_private_synthetic_misroute(self):
        self.bad(lambda d:d["tasks"][0].__setitem__("classification","PRIVATE"))

    def test_private_admitted_guest_cannot_self_admit(self):
        self.bad(lambda d:d["tasks"][0].__setitem__("runtime","private-admitted-guest"))

    def test_source_file_collision(self):
        self.bad(lambda d:d["tasks"][1].__setitem__("scope",["qualification/synthetic_fixture_one/"]))

    def test_parent_source_overlap(self):
        self.bad(lambda d:d["tasks"][1].__setitem__("scope",["qualification/"]))

    def test_tampered_sha(self):
        self.bad(lambda d:d["tasks"][1].__setitem__("source_sha","latest"))

    def test_readiness_dependency_unknown(self):
        self.bad(lambda d:d["tasks"][1].__setitem__("depends_on",["B03-H1-GUEST"]))

    def test_public_runner_permission(self):
        self.bad(lambda d:d.__setitem__("public_host_effects",True))


if __name__=="__main__":
    unittest.main()
