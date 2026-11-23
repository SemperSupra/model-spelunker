import copy
from pathlib import Path
import unittest
import priority_probe as p

def trial(mode):
    rows=[]
    for idx,name in enumerate(("batch-1","batch-2","interactive")):
        kind="interactive" if idx==2 else "batch"
        yes=(mode=="baseline" and idx in (0,1)) or (mode=="reserved" and idx in (0,2))
        offer=150.0 if idx==2 else idx*.5
        finish=(1000.0+idx*250) if yes else (50.0 if idx==1 else 152.0)
        rows.append({"job":name,"class":kind,"http_status":200 if yes else 503,
         "offered_offset_ms":offer,"finished_offset_ms":finish,
         "ttft_ms":100.0 if yes else None,
         "prompt_tokens":500 if yes and kind=="batch" else (40 if yes else 0),
         "output_tokens":64 if yes and kind=="batch" else (8 if yes else 0),
         "deliberately_spoofed_untrusted_x_class":"interactive" if kind=="batch" else "batch"})
    return {"mode":mode,"observations":rows,"wall_ms":1300.0}

class PriorityTests(unittest.TestCase):
    def test_two_existing_nginx_treatments_independently_falsifiable(self):
        a,b=trial("baseline"),trial("reserved")
        self.assertEqual(p.validate_pair(a,b),"CERT_BOUND_INTERACTIVE_ADMISSION_SCREEN_PASS")
        self.assertEqual([r["http_status"] for r in a["observations"]],[200,200,503])
        self.assertEqual([r["http_status"] for r in b["observations"]],[200,503,200])
    def test_inverted_interactive_benefit_is_rejected(self):
        a,b=trial("baseline"),trial("reserved")
        a["observations"][2].update(http_status=200,ttft_ms=10.0,output_tokens=8,prompt_tokens=40)
        b["observations"][2].update(http_status=503,ttft_ms=None,output_tokens=0,prompt_tokens=0)
        self.assertEqual(p.validate_pair(a,b),"INVERTED_BENEFIT")
    def test_bad_comparisons_are_not_silently_accepted(self):
        a,b=trial("baseline"),trial("reserved")
        for mutation in (
          lambda x,y:y["observations"].pop(),
          lambda x,y:y["observations"][2].update(job="batch-1"),
          lambda x,y:y["observations"][0].update(http_status=401),
          lambda x,y:y["observations"][0].update(finished_offset_ms=-1.0),
          lambda x,y:y["observations"][0].update(prompt_tokens=777),
          lambda x,y:y["observations"][2].update(offered_offset_ms=0.0),
        ):
            x,y=copy.deepcopy(a),copy.deepcopy(b)
            mutation(x,y)
            with self.subTest(mutation=repr(mutation)):
                with self.assertRaises(ValueError):
                    p.validate_pair(x,y)
    def test_untrusted_request_header_does_not_define_role_in_source_config(self):
        config=(Path(__file__).parent/"nginx-r15.conf").read_text()
        self.assertIn("$ssl_client_verify:$ssl_client_s_dn",config)
        self.assertIn("limit_conn r15_batch_reserved 1;",config)
        self.assertIn("limit_conn r15_global_reserved 2;",config)
        self.assertIn("proxy_set_header X-Class \"\";",config)
        self.assertNotIn("map $http_x_class",config)
    def test_unknown_certificate_cannot_be_reclassified_as_interactive(self):
        from unittest.mock import patch
        def result(mode,_clients):return trial(mode)
        # All two-class observations look successful, but a third valid-CA
        # certificate obtaining HTTP 200 MUST invalidate that verdict.
        negatives=[{"denied":False,"status":200},{"denied":True,"status":400},{"denied":True,"status":400}]
        with patch.object(p.auth,"tls_opener",return_value=object()), \
             patch.object(p.auth,"auth_rejection",side_effect=negatives), \
             patch.object(p,"trial",side_effect=result):
            with self.assertRaises(ValueError):
                p.experiment("/tmp/ephemeral-source-only")
if __name__=="__main__":unittest.main()
