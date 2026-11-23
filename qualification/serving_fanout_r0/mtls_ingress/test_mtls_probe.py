import copy
import unittest
import mtls_probe as p

def make(labels, accepted):
    rows=[]
    for i,name in enumerate(labels):
        yes=i in accepted
        rows.append({"client_certificate_label":name,"request_index":i,
            "http_status":200 if yes else 503,
            "offered_offset_ms":i*.2,
            "finished_offset_ms":1000.0+i*200,
            "ttft_ms":22.0 if yes else None,
            "output_tokens":64 if yes else 0,
            "spoofed_header_claimed_other_identity":True})
    return rows

def samples():
    solo=make(["alpha"]*3,{0,1})
    mixed=make(["alpha"]*3+["beta"]*3+["gamma"]*3,{0,1,3,6})
    return solo,mixed

def auth():
    return {"no_client_certificate":{"denied":True,"status":400},
        "untrusted_client_certificate":{"denied":True,"status":400}}

class CertificateQuotaTests(unittest.TestCase):
    def test_two_distinct_limits_independently_exercised(self):
        solo,mixed=samples()
        self.assertEqual(p.verdict(solo,mixed,auth()),"MTLS_CERT_AND_GLOBAL_CAP_SCREEN_PASS")
        self.assertEqual(sum(r["http_status"]==200 for r in solo),2)
        self.assertEqual(sum(r["http_status"]==200 for r in mixed),4)
    def test_single_certificate_cannot_exceed_two(self):
        solo,mixed=samples()
        solo[2].update(http_status=200,ttft_ms=1.0,output_tokens=64)
        self.assertEqual(p.verdict(solo,mixed,auth()),"FAIL_PER_CERT_LIMIT")
    def test_mixed_certificate_quota_does_not_follow_spoofable_headers(self):
        solo,mixed=samples()
        mixed[2].update(http_status=200,ttft_ms=1.0,output_tokens=64)
        mixed[3].update(http_status=503,ttft_ms=None,output_tokens=0)
        self.assertEqual(p.verdict(solo,mixed,auth()),"FAIL_PER_CERT_LIMIT")
    def test_global_bound_is_independently_falsifiable(self):
        solo,mixed=samples()
        # 2 alpha + 2 beta + 1 gamma = 5 globally, but <=2 per identity.
        mixed[4].update(http_status=200,ttft_ms=1.0,output_tokens=64)
        self.assertEqual(p.verdict(solo,mixed,auth()),"FAIL_GLOBAL_LIMIT")
    def test_unauthorized_must_not_pass(self):
        solo,mixed=samples()
        state=auth();state["no_client_certificate"]={"denied":False,"status":200}
        self.assertEqual(p.verdict(solo,mixed,state),"FAIL_CREDENTIAL_AUTHENTICATION")
    def test_forged_receipts_fail_closed(self):
        cases=[
          lambda s,m: m.pop(),
          lambda s,m: m[8].update(request_index=0),
          lambda s,m: m[8].update(client_certificate_label="delta"),
          lambda s,m: m[4].update(http_status=401),
          lambda s,m: m[3].update(output_tokens=0),
          lambda s,m: s[1].update(finished_offset_ms=-1),
        ]
        for mutate in cases:
            with self.subTest(case=repr(mutate)):
                solo,mixed=samples();mutate(solo,mixed)
                with self.assertRaises(ValueError):
                    p.verdict(solo,mixed,auth())
    def test_skew_and_underutilization_are_not_success(self):
        solo,mixed=samples()
        mixed[-1]["offered_offset_ms"]=700.0
        self.assertEqual(p.verdict(solo,mixed,auth()),"INCONCLUSIVE_NONOVERLAPPING_OFFERS")
        solo,mixed=samples()
        solo[1].update(http_status=503,ttft_ms=None,output_tokens=0)
        self.assertEqual(p.verdict(solo,mixed,auth()),"INCONCLUSIVE_SINGLE_CERT_UNDERUTILIZATION")
    def test_strict_tls_client_identity(self):
        import inspect
        source=inspect.getsource(p.tls_opener)
        self.assertIn("ssl.create_default_context",source)
        self.assertIn("check_hostname=True",source)
        self.assertNotIn("CERT_NONE",source)
if __name__=="__main__":unittest.main()
