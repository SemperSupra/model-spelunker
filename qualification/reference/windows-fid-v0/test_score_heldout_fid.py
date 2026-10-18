#!/usr/bin/env python3
"""Public synthetic oracle controls; no actual native-Ghidra qualification implied."""
import unittest
from score_heldout_fid import evaluate

MAP = """ 0001:00000000 _good 0000000140001000 f libcmt:good.obj
 0001:00000020 _different 0000000140001020 f libcmt:bad.obj
 0001:00000040 _unique 0000000140001040 f libcmt:uniq.obj
"""
def query():
    return """RE_SHIPPED_FID_MATCH=140001000|_good|10.0|vs|2019|x64|3
RE_SHIPPED_FID_MATCH=140001020|_wrong|10.0|vs|2019|x64|2
RE_SHIPPED_FID_MATCH=140001040|_unique|9.0|vs|2019|x64|1
RE_SHIPPED_FID_TIE_GROUP=140001000|3|1|2
RE_SHIPPED_FID_TIE_GROUP=140001020|2|2|2
RE_SHIPPED_FID_TIE_CONSENSUS=1
RE_SHIPPED_FID_TIE_CONFLICT=1
RE_SHIPPED_FID_MATCH_COUNT=3
RE_SHIPPED_FID_AMBIGUOUS_COUNT=2
"""

class HeldoutOracle(unittest.TestCase):
    def test_positive_observation_not_admission(self):
        result=evaluate(MAP, query(), "static_heldout")
        m=result["metrics"]
        self.assertEqual(m["consensus_exact_crt"], 1)
        self.assertEqual(m["unique_exact_crt"], 1)
        self.assertEqual(m["conflicting_abstain"], 1)
        self.assertFalse(result["automatic_naming_permitted"])

    def test_consensus_wrong_name_is_not_silently_accepted(self):
        m=evaluate(MAP.replace("_good ", "_other "), query(), "static_heldout")["metrics"]
        self.assertEqual(m["consensus_wrong_crt"], 1)

    def test_missing_group_fails(self):
        with self.assertRaises(ValueError):
            evaluate(MAP, query().replace("RE_SHIPPED_FID_TIE_GROUP=140001000|3|1|2\n", ""), "static")

    def test_counter_forgery_fails(self):
        with self.assertRaises(ValueError):
            evaluate(MAP, query().replace("MATCH_COUNT=3", "MATCH_COUNT=30"), "static")

    def test_conflicting_group_cannot_be_relabelled_consensus(self):
        with self.assertRaises(ValueError):
            evaluate(MAP, query().replace("140001020|2|2|2", "140001020|2|1|2"), "static")

    def test_duplicate_address_fails(self):
        with self.assertRaises(ValueError):
            evaluate(MAP, query().replace("RE_SHIPPED_FID_TIE_GROUP=140001000",
                "RE_SHIPPED_FID_MATCH=140001000|_wrong|10.0|vs|2019|x64|3\nRE_SHIPPED_FID_TIE_GROUP=140001000"), "static")
if __name__ == "__main__":
    unittest.main()
