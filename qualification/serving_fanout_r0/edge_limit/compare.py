#!/usr/bin/env python3
"""Independent admission-status reduction of direct vs off-the-shelf nginx receipts."""
import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_SOURCE="REAL_PUBLIC_CPU_HOT_LOADED_OLLAMA_QUEUE_LIMIT_EXPLORATORY"
EXPECTED_MODEL="8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"

def check(one):
    if one.get("evidence_class")!=EXPECTED_SOURCE:
        raise ValueError("unsupported evidence provenance")
    if one.get("exact_model_digest")!=EXPECTED_MODEL:
        raise ValueError("mismatched model representation")
    if one.get("expected_parallel")!=1 or one.get("configured_max_queue")!=1:
        raise ValueError("wrong backend admission configuration")
    rows=one.get("observations")
    if not isinstance(rows,list) or len(rows)!=6:
        raise ValueError("missing or extra measured requests")
    if {r.get("request_index") for r in rows}!={0,1,2,3,4,5}:
        raise ValueError("duplicate or incomplete request identifiers")
    statuses=[r.get("http_status") for r in rows]
    if any(x not in (200,429,503) for x in statuses):
        raise ValueError("unexpected HTTP result")
    for r in rows:
        if not isinstance(r.get("offered_offset_ms"),(float,int)) or not isinstance(r.get("finished_offset_ms"),(float,int)):
            raise ValueError("missing monotonic time")
        if r["finished_offset_ms"]<=r["offered_offset_ms"]:
            raise ValueError("completion preceding arrival")
    spread=max(r["offered_offset_ms"] for r in rows)-min(r["offered_offset_ms"] for r in rows)
    overlap=min(r["finished_offset_ms"] for r in rows)>max(r["offered_offset_ms"] for r in rows)
    accepted=statuses.count(200)
    rejected=statuses.count(503)+statuses.count(429)
    return {"accepted":accepted,"rejected":rejected,"arrival_spread_ms":round(spread,3),
            "all_offered_before_first_completion":overlap,
            "controlled_arrival":bool(overlap and spread<=500)}

def compare(direct,edge,nginx_version,config_sha):
    a,b=check(direct),check(edge)
    if direct.get("source_sha")!=edge.get("source_sha") or direct.get("run_id")!=edge.get("run_id"):
        raise ValueError("different-source or different-run compare not admitted")
    if direct.get("host")!=edge.get("host"):
        raise ValueError("cross-host comparison not admissible")
    if not isinstance(nginx_version,str) or not nginx_version.startswith("nginx version:"):
        raise ValueError("unverified nginx binary version")
    if len(config_sha)!=64 or any(c not in "0123456789abcdef" for c in config_sha):
        raise ValueError("invalid config hash")
    if not a["controlled_arrival"] or not b["controlled_arrival"]:
        outcome="INCONCLUSIVE_ARRIVAL_INTERFERENCE"
    elif a["accepted"]>2 and b["accepted"]<=2 and b["rejected"]>=4:
        outcome="NGINX_LOOPBACK_GLOBAL_IP_LIMIT_SCREEN_PASS"
    elif b["accepted"]>2:
        outcome="NGINX_LOOPBACK_ADMISSION_CAP_FALSIFIED"
    else:
        outcome="INCONCLUSIVE_NATIVE_BASELINE_NOT_EXCEEDING_BOUND"
    return {"evidence_class":"OFF_THE_SHELF_LOOPBACK_ADMISSION_COMPARISON_EXPLORATORY",
       "direct":a,"nginx_edge":b,"outcome":outcome,"nginx_version":nginx_version,
       "nginx_config_sha256":config_sha,"source_sha":direct["source_sha"],
       "backend_model_digest":EXPECTED_MODEL,
       "host":direct["host"],"production_admission":"NOT_APPROVED",
       "tenant_identity":"NOT_VALIDATED_SOURCE_IP_ONLY",
       "queue_priority":"NOT_TESTED","cache_kv_hit_rate":"NOT_OBSERVED"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--direct",type=Path,required=True)
    p.add_argument("--edge",type=Path,required=True)
    p.add_argument("--nginx-version",type=Path,required=True)
    p.add_argument("--config",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    direct=json.loads(a.direct.read_text())
    edge=json.loads(a.edge.read_text())
    verdict=compare(direct,edge,a.nginx_version.read_text().strip(),
        hashlib.sha256(a.config.read_bytes()).hexdigest())
    a.out.write_text(json.dumps(verdict,sort_keys=True,indent=2)+"\n")
    print("ADMISSION_EXPERIMENT="+verdict["outcome"])
    print("NATIVE_200=%d NATIVE_REJECT=%d PROXY_200=%d PROXY_REJECT=%d"%(
        verdict["direct"]["accepted"],verdict["direct"]["rejected"],
        verdict["nginx_edge"]["accepted"],verdict["nginx_edge"]["rejected"]))
if __name__=="__main__":
    main()
