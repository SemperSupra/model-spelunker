#!/usr/bin/env python3
"""W-7 independent linker-MAP alias oracle controls (no PE/Ghidra download)."""
import unittest
from verify_bundled_crt_fid import classify_linker_match

class W7LinkerOracle(unittest.TestCase):
    def test_single_verified_crt_identity(self):
        self.assertEqual(classify_linker_match({("_good","libcmt","good.obj")},"_good"),
                         ("TP_EXACT_CRT",False))
        self.assertEqual(classify_linker_match({("_good","libcmt","good.obj")},"_false"),
                         ("MISMATCH_CRT",False))
    def test_mixed_library_alias_abstains_in_both_orders(self):
        for records in (
            [("_good","libcmt","good.obj"),("_decoy","userlib","fake.obj")],
            [("_decoy","userlib","fake.obj"),("_good","libcmt","good.obj")],
        ):
            self.assertEqual(classify_linker_match(set(records),"_good"),
                             ("MAP_ALIAS_ABSTAIN",True))
            self.assertEqual(classify_linker_match(set(records),"_decoy"),
                             ("MAP_ALIAS_ABSTAIN",True))
    def test_two_crt_aliases_abstain(self):
        x={("_first","libucrt","a.obj"),("_other","libcmt","b.obj")}
        self.assertEqual(classify_linker_match(x,"_first"),
                         ("MAP_ALIAS_ABSTAIN",True))
    def test_same_symbol_object_repeat_is_not_an_alias(self):
        x={("_good","libcmt","a.obj"),("_good","libcmt","b.obj")}
        self.assertEqual(classify_linker_match(x,"_good"),
                         ("TP_EXACT_CRT",False))
    def test_unknown_and_noncrt_are_not_fid_truth(self):
        self.assertEqual(classify_linker_match(set(),"_good"),
                         ("UNATTRIBUTED_OR_NONCRT",False))
        self.assertEqual(classify_linker_match({("_mine","my.lib","a.obj")},"_mine"),
                         ("UNATTRIBUTED_OR_NONCRT",False))

if __name__ == "__main__":
    unittest.main()
