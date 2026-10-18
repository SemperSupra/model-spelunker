#!/usr/bin/env python3
"""Deterministic W-4 negative controls, no Ghidra download or proprietary sample."""
import importlib.util
import unittest
from pathlib import Path

p=Path(__file__).with_name("triage_bundled_crt_fid.py")
spec=importlib.util.spec_from_file_location("fid_w4",p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def candidate(addr,name,ties,classification):
    return {"address":addr,"candidate":name,"ties":ties,
            "classification":classification,"score":33.0}
def fixture():
    return {"schema_version":1,"evaluated":{
        "static":{"fid_matches":4,"bounded_candidates":[
            candidate("1000","_known",1,"TP_EXACT_CRT"),
            candidate("1008","_different",1,"MISMATCH_CRT"),
            candidate("1010","_tie",2,"TP_EXACT_CRT"),
            candidate("1018","_unknown",1,"UNATTRIBUTED_OR_NONCRT")]},
        "dynamic":{"fid_matches":1,"bounded_candidates":[
            candidate("2000","_import_thunk",3,"UNATTRIBUTED_OR_NONCRT")]}}}

class W4Control(unittest.TestCase):
    def test_strict_abstentions(self):
        r=mod.assess(fixture())
        w=r["observed"]["static"]
        self.assertEqual((w["unambiguous"],w["ambiguous_abstentions"]),(3,1))
        self.assertEqual((w["exact_unique_calibration_only"],w["wrong_name_unique"],w["unattributed_unique"]),(1,1,1))
        self.assertFalse(w["auto_apply_permitted"])
        self.assertIsNone(r["observed"]["dynamic"]["precision_on_known_unique"])
        self.assertFalse(r["gates"]["correctly_named_unique_matches_sufficient_for_promotion"])
    def test_duplicate_addresses_fail(self):
        bad=fixture()
        bad["evaluated"]["static"]["bounded_candidates"][1]["address"]="1000"
        with self.assertRaises(ValueError):mod.assess(bad)
    def test_unscorable_tie_or_label_fails(self):
        for field,value in (("ties",0),("classification","AUTO_ACCEPT")):
            with self.subTest(field=field):
                bad=fixture()
                bad["evaluated"]["static"]["bounded_candidates"][0][field]=value
                with self.assertRaises(ValueError):mod.assess(bad)
    def test_missing_rows_cannot_be_silent(self):
        r=fixture()
        r["evaluated"]["static"]["fid_matches"]=8
        a=mod.assess(r)
        self.assertEqual(a["observed"]["static"]["unobserved_rows"],4)
        self.assertEqual(a["status"],"W4_UNIQUE_CANDIDATE_CALIBRATION_ONLY")
if __name__=="__main__":unittest.main()
