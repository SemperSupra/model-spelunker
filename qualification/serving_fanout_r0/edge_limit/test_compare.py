import copy
import unittest
import compare as m

def synthetic(status):
    rows=[]
    for i,s in enumerate(status):
        rows.append({"request_index":i,"http_status":s,"offered_offset_ms":i*.1,
                     "finished_offset_ms":1000+i*300,"ttft_ms":None if s!=200 else 100,
                     "input_tokens":503 if s==200 else 0,"output_tokens":64 if s==200 else 0})
    return {"evidence_class":m.EXPECTED_SOURCE,"exact_model_digest":m.EXPECTED_MODEL,
         "expected_parallel":1,"configured_max_queue":1,"run_id":"same-run",
         "source_sha":"full-same-source-identity",
         "host":{"cpu_model":"public-synthetic"},"observations":rows}
class ProofTests(unittest.TestCase):
    def test_realistic_hot_bypass_plus_edge_bound(self):
        d=synthetic([200]*6)
        e=synthetic([200,200,503,503,503,503])
        r=m.compare(d,e,"nginx version: nginx/1.24.0","c"*64)
        self.assertEqual(r["outcome"],"NGINX_LOOPBACK_GLOBAL_IP_LIMIT_SCREEN_PASS")
        self.assertEqual(r["direct"]["accepted"],6)
        self.assertEqual(r["nginx_edge"]["rejected"],4)
        self.assertEqual(r["production_admission"],"NOT_APPROVED")
    def test_forged_edge_and_skew_not_accepted(self):
        d=synthetic([200]*6)
        e=synthetic([200]*6)
        self.assertEqual(m.compare(d,e,"nginx version: nginx/1.24.0","c"*64)["outcome"],
                         "NGINX_LOOPBACK_ADMISSION_CAP_FALSIFIED")
        e=synthetic([200,200,503,503,503,503])
        e["observations"][-1]["offered_offset_ms"]=2000
        self.assertEqual(m.compare(d,e,"nginx version: nginx/1.24.0","c"*64)["outcome"],
                         "INCONCLUSIVE_ARRIVAL_INTERFERENCE")
    def test_identity_and_provenance_fail_closed(self):
        d=synthetic([200]*6);e=synthetic([200,200,503,503,503,503])
        for case in ("host","source","model","duplicate","digest"):
            a,b=copy.deepcopy(d),copy.deepcopy(e)
            if case=="host":b["host"]["cpu_model"]="different"
            if case=="source":b["source_sha"]="different"
            if case=="model":b["exact_model_digest"]="changed"
            if case=="duplicate":b["observations"][-1]["request_index"]=0
            if case=="digest":
                with self.assertRaises(ValueError):
                    m.compare(a,b,"nginx version: nginx/1.24.0","bad")
                continue
            with self.assertRaises(ValueError):
                m.compare(a,b,"nginx version: nginx/1.24.0","c"*64)
if __name__=="__main__":
    unittest.main()
