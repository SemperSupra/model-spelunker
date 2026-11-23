import copy
import unittest
import mtls_probe as p

def sample():
    rows=[]
    for i in range(8):
        name="alpha" if i<4 else "beta"
        admit=i in (0,1,4,5)
        rows.append({
           "client_certificate_label":name,"request_index":i,
           "http_status":200 if admit else 503,
           "offered_offset_ms":float(i)*.2,
           "finished_offset_ms":1000.0+float(i)*200,
           "ttft_ms":22.0 if admit else None,
           "output_tokens":64 if admit else 0,
           "spoofed_header_claimed_other_identity":True})
    return rows

def auth():
    return {"no_client_certificate":{"denied":True,"status":400},
            "untrusted_client_certificate":{"denied":True,"status":400}}

class CertificateQuotaTests(unittest.TestCase):
    def test_positive_two_per_certificate_and_four_global(self):
        rows=sample()
        self.assertEqual(p.verdict(rows,auth()),"MTLS_CERT_AND_GLOBAL_CAP_SCREEN_PASS")
        self.assertEqual(sum(x["http_status"]==200 for x in rows),4)
    def test_one_identity_can_not_consume_another_identity_quota(self):
        rows=sample()
        rows[2]["http_status"]=200;rows[2]["ttft_ms"]=1.0;rows[2]["output_tokens"]=64
        rows[4]["http_status"]=503;rows[4]["ttft_ms"]=None;rows[4]["output_tokens"]=0
        self.assertEqual(p.verdict(rows,auth()),"FAIL_PER_CERT_LIMIT")
    def test_global_overadmission_is_rejected(self):
        rows=sample()
        rows[6]["http_status"]=200;rows[6]["ttft_ms"]=1.0;rows[6]["output_tokens"]=64
        self.assertEqual(p.verdict(rows,auth()),"FAIL_GLOBAL_LIMIT")
    def test_unauthenticated_request_cannot_be_excused_by_quota(self):
        a=auth();a["no_client_certificate"]={"denied":False,"status":200}
        self.assertEqual(p.verdict(sample(),a),"FAIL_CREDENTIAL_AUTHENTICATION")
    def test_forged_representations_rejected(self):
        mutations=[
          lambda rows: rows.pop(),
          lambda rows: rows[7].update(request_index=0),
          lambda rows: rows[7].update(client_certificate_label="synthetic-gamma"),
          lambda rows: rows[4].update(http_status=401),
          lambda rows: rows[0].update(output_tokens=0),
          lambda rows: rows[1].update(finished_offset_ms=-1),
        ]
        for mutate in mutations:
            with self.subTest(mutate=repr(mutate)):
                rows=sample();mutate(rows)
                with self.assertRaises(ValueError):
                    p.verdict(rows,auth())
    def test_uncontrolled_offer_skew_cannot_be_treated_as_pass(self):
        rows=sample();rows[-1]["offered_offset_ms"]=700.0
        self.assertEqual(p.verdict(rows,auth()),"INCONCLUSIVE_NONOVERLAPPING_OFFERS")
    def test_certificate_paths_required_in_pair(self):
        with self.assertRaises(ValueError):
            p.tls_opener("/nonexistent/ca.crt","client.crt")
    def test_strict_trust_not_insecure_tls(self):
        import inspect
        src=inspect.getsource(p.tls_opener)
        self.assertIn("ssl.create_default_context",src)
        self.assertIn("check_hostname=True",src)
        self.assertNotIn("CERT_NONE",src)
if __name__=="__main__":unittest.main()
