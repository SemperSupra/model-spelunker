"""Negative controls for the DeepSeek BYOK expenditure and authority gate."""
from datetime import datetime, timedelta, timezone
import unittest

from qualification.hosted_paid_route_gate import (
    CANDIDATE, MODEL, COST_CLASS, RouteNotAdmitted, admit_deepseek_paid_route
)

NOW=datetime(2026,10,18,12,0,0,tzinfo=timezone.utc)
def fixture():
    return {
        "candidate_id":CANDIDATE,
        "model_id":MODEL,
        "cost_class":COST_CLASS,
        "extra_body":{"provider":{"only":["deepseek"],"allow_fallbacks":False,
                                   "data_collection":"deny"}},
        "key_info":{
            "is_management_key":False,
            "is_provisioning_key":False,
            "include_byok_in_limit":True,
            "limit":0.10,
            "limit_remaining":0.08,
            "limit_reset":None,
            "expires_at":(NOW+timedelta(minutes=20)).isoformat().replace("+00:00","Z")
        },
        "model_data":{"id":MODEL,"supported_parameters":["tools","temperature"]},
        "now":NOW,
    }

class PaidRouteControls(unittest.TestCase):
    def test_qualified_child_route(self):
        result=admit_deepseek_paid_route(**fixture())
        self.assertTrue(result["ready"])
        self.assertFalse(result["actual_byok_billing_verified"])
    def test_unlimited_parent_denied(self):
        f=fixture();f["key_info"]["limit"]=None
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_higher_spend_cap_denied(self):
        f=fixture();f["key_info"]["limit"]=1.0
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_key_remaining_cannot_exceed_limit(self):
        f=fixture();f["key_info"]["limit_remaining"]=10.0
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_disallow_management_key(self):
        f=fixture();f["key_info"]["is_management_key"]=True
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_refuse_byok_not_counted(self):
        f=fixture();f["key_info"]["include_byok_in_limit"]=False
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_reset_cannot_replenish_budget(self):
        f=fixture();f["key_info"]["limit_reset"]="daily"
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_expired_or_unbounded_key_denied(self):
        for minutes in (-5,0,120):
            f=fixture()
            f["key_info"]["expires_at"]=(NOW+timedelta(minutes=minutes)).isoformat().replace("+00:00","Z")
            with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_provider_substitution_denied(self):
        f=fixture();f["extra_body"]["provider"]["only"]=["wafer"]
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_shared_provider_fallback_denied(self):
        f=fixture();f["extra_body"]["provider"]["allow_fallbacks"]=True
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_required_data_collection_policy(self):
        f=fixture();f["extra_body"]["provider"].pop("data_collection")
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_model_tools_required(self):
        f=fixture();f["model_data"]["supported_parameters"]=[]
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_unknown_model_not_metered(self):
        f=fixture();f["model_id"]="deepseek/other"
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)
    def test_unknown_candidate_never_overrides_free(self):
        f=fixture();f["candidate_id"]="openrouter/free"
        with self.assertRaises(RouteNotAdmitted):admit_deepseek_paid_route(**f)

if __name__=="__main__":
    unittest.main()
