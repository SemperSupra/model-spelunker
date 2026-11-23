#!/usr/bin/env python3
"""R13: synthetic public-CPU, mTLS-bound certificate admission. No production traffic."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "streaming"))
import streaming_probe as base

CLIENTS=("alpha","beta","gamma")
PER_CERT_LIMIT=2
GLOBAL_LIMIT=4
REQUESTS_PER_CERT=3
EXPECTED_DIGEST="8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None

def tls_opener(ca, cert=None, key=None):
    ctx=ssl.create_default_context(ssl.Purpose.SERVER_AUTH,cafile=str(ca))
    ctx.check_hostname=True
    if (cert is None)!=(key is None):
        raise ValueError("certificate and private key required together")
    if cert is not None:
        ctx.load_cert_chain(certfile=str(cert),keyfile=str(key))
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx),NoRedirect())

def prompt(index):
    words=("amber cedar orbit vector signal field lunar delta pixel cobalt")
    return "Synthetic R13 only; request %02d. "%index + (words+" ")*35 + \
      "Describe ten concrete reliability checks in a detailed numbered list; do not stop early."

def one_request(target,client,client_name,index,gate,origin):
    payload={"model":"qwen3:1.7b","prompt":prompt(index),"stream":True,"think":False,
             "keep_alive":"10m","options":{"num_ctx":2048,"num_predict":64,"temperature":0}}
    body=json.dumps(payload).encode()
    # Deliberate hostile header: it cannot change TLS certificate fingerprint.
    claimed={"alpha":"beta","beta":"gamma","gamma":"alpha"}[client_name]
    req=urllib.request.Request(target+"/api/generate",data=body,
        headers={"Content-Type":"application/json","X-Tenant":claimed})
    try:
        gate.wait(timeout=15)
    except threading.BrokenBarrierError as exc:
        raise RuntimeError("unsynchronized offered requests") from exc
    started=time.monotonic()
    first=None;finished=None;tokens=0;status=None
    try:
        with client.open(req,timeout=150) as response:
            status=response.status
            for line in response:
                if len(line)>1048576:raise RuntimeError("oversized response")
                item=json.loads(line)
                if item.get("response") and first is None:first=time.monotonic()-started
                if item.get("done"):
                    finished=time.monotonic()
                    tokens=int(item.get("eval_count",0))
            if status==200 and (first is None or finished is None or tokens<1):
                raise RuntimeError("success missing model completion/first token")
    except urllib.error.HTTPError as err:
        if err.code!=503:raise RuntimeError("unexpected HTTP code %d"%err.code) from err
        status=err.code;finished=time.monotonic()
    if status not in (200,503) or finished is None:
        raise RuntimeError("invalid completed status")
    return {"client_certificate_label":client_name,
        "request_index":index,"http_status":status,
        "offered_offset_ms":round((started-origin)*1000,3),
        "finished_offset_ms":round((finished-origin)*1000,3),
        "ttft_ms":None if first is None else round(first*1000,3),
        "output_tokens":tokens,
        "spoofed_header_claimed_other_identity":True}

def auth_rejection(target,client):
    request=urllib.request.Request(target+"/api/tags")
    try:
        with client.open(request,timeout=12) as response:
            return {"denied":False,"status":response.status}
    except urllib.error.HTTPError as err:
        if err.code not in (400,401,403,495,496):raise
        return {"denied":True,"kind":"HTTP_REJECTED","status":err.code}
    except (urllib.error.URLError,ssl.SSLError,ConnectionError,OSError) as err:
        # TLS alerts / abrupt close are also fail-closed; do not record secrets.
        return {"denied":True,"kind":"TLS_CONNECTION_REJECTED","exception":type(err).__name__}

def validate_overlap(rows,expected_labels):
    if len(rows)!=len(expected_labels) or len({x["request_index"] for x in rows})!=len(rows):
        raise ValueError("missing or duplicate offered request")
    if sorted(x["client_certificate_label"] for x in rows)!=sorted(expected_labels):
        raise ValueError("forged certificate-label coverage")
    for row in rows:
        if row["client_certificate_label"] not in CLIENTS:raise ValueError("unknown cert identity")
        if row["http_status"] not in (200,503):raise ValueError("unrecognized status")
        if row["finished_offset_ms"]<=row["offered_offset_ms"]:raise ValueError("clock inversion")
        if row["http_status"]==200 and (row["output_tokens"]<1 or row["ttft_ms"] is None):
            raise ValueError("accepted response missing completion")
    offered=[x["offered_offset_ms"] for x in rows]
    return max(offered)-min(offered)<=500 and min(x["finished_offset_ms"] for x in rows)>max(offered)

def verdict(solo,mixed,auth):
    solo_overlap=validate_overlap(solo,["alpha"]*3)
    mixed_overlap=validate_overlap(mixed,[c for c in CLIENTS for _ in range(3)])
    if not all(x.get("denied") is True for x in auth.values()):
        return "FAIL_CREDENTIAL_AUTHENTICATION"
    if not solo_overlap or not mixed_overlap:
        return "INCONCLUSIVE_NONOVERLAPPING_OFFERS"
    one=sum(x["http_status"]==200 for x in solo)
    if one>PER_CERT_LIMIT:return "FAIL_PER_CERT_LIMIT"
    if one<PER_CERT_LIMIT:return "INCONCLUSIVE_SINGLE_CERT_UNDERUTILIZATION"
    multi={c:sum(x["http_status"]==200 and x["client_certificate_label"]==c for x in mixed)
           for c in CLIENTS}
    if any(v>PER_CERT_LIMIT for v in multi.values()):
        return "FAIL_PER_CERT_LIMIT"
    admitted=sum(multi.values())
    if admitted>GLOBAL_LIMIT:return "FAIL_GLOBAL_LIMIT"
    if admitted==4 and sum(x["http_status"]==503 for x in mixed)==5:
        return "MTLS_CERT_AND_GLOBAL_CAP_SCREEN_PASS"
    return "INCONCLUSIVE_GLOBAL_UNDERUTILIZATION"

def burst(target,clients,assignments):
    gate=threading.Barrier(len(assignments))
    started=time.monotonic()
    with ThreadPoolExecutor(max_workers=len(assignments)) as executor:
        futures=[executor.submit(one_request,target,clients[c],c,i,gate,started)
                 for i,c in assignments]
        rows=[f.result() for f in futures]
    return sorted(rows,key=lambda x:x["request_index"])

def experiment(cert_dir,target):
    if target!="https://127.0.0.1:18443":
        raise ValueError("exact loopback HTTPS origin only")
    cert_dir=Path(cert_dir)
    ca=cert_dir/"ca.crt"
    clients={c:tls_opener(ca,cert_dir/(c+".crt"),cert_dir/(c+".key")) for c in CLIENTS}
    auth={
      "no_client_certificate":auth_rejection(target,tls_opener(ca)),
      "untrusted_client_certificate":auth_rejection(
          target,tls_opener(ca,cert_dir/"rogue.crt",cert_dir/"rogue.key")),
    }
    # Two independent falsification trials, SAME ingress + actual backend.
    solo=burst(target,clients,[(i,"alpha") for i in range(3)])
    mixed=burst(target,clients,[(i,c) for i,c in enumerate(
        tuple(label for label in CLIENTS for _ in range(3)))])
    state=verdict(solo,mixed,auth)
    return {"evidence_class":"PUBLIC_CPU_REAL_MTLS_CERT_ADMISSION_EXPLORATORY",
       "source_sha":os.getenv("GITHUB_SHA","UNKNOWN"),
       "run_id":os.getenv("GITHUB_RUN_ID","UNKNOWN"),
       "nginx_rule":"verified_tls_client_cert_fingerprint_per_cert_2_and_server_name_global_4",
       "configured_per_certificate":PER_CERT_LIMIT,"configured_global":GLOBAL_LIMIT,
       "subject_mapping_to_governed_tenant":"NOT_QUALIFIED",
       "certificate_rotation_revocation":"NOT_QUALIFIED",
       "source_ip_identity":"NOT_USED_FOR_PER_CERT_LIMIT",
       "model_runtime_digest":EXPECTED_DIGEST,
       "raw_certificates_and_keys":"NEVER_LOGGED_OR_ARCHIVED",
       "observed_authorization_negatives":auth,
       "single_cert_probe":solo,
       "mixed_cert_probe":mixed,"result":state,"production_admission":"NO_PROMOTION"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cert-dir",type=Path,required=True)
    p.add_argument("--base",default="https://127.0.0.1:18443")
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    report=experiment(args.cert_dir,args.base)
    data=json.dumps(report,sort_keys=True,indent=2)+"\n"
    args.out.write_text(data)
    print("R13_MTLS_RESULT="+report["result"])
    print("R13_ADMITTED=%d REJECTED=%d"%(sum(r["http_status"]==200 for r in report["single_cert_probe"]+report["mixed_cert_probe"]),sum(r["http_status"]==503 for r in report["single_cert_probe"]+report["mixed_cert_probe"])))
    print("R13_RECEIPT_SHA256="+hashlib.sha256(data.encode()).hexdigest())
if __name__=="__main__":
    main()
