"""Read-only, portable projection of canonical interview receipts.
No service, scheduler, registry, live credentials or qualification promotion.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
CAPABILITIES={"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","commands":{"discover":{"purpose":"Find supported interfaces","side_effects":"none"},"status":{"purpose":"Inspect a bounded receipt directory","side_effects":"none"},"evidence":{"purpose":"Resolve one run receipt and exact SHA-256","side_effects":"none"},"render":{"purpose":"Generate a standalone read-only HTML view","side_effects":"writes requested output file"}},"not_supported":["execution","authorization","operational promotion"],"errors":{"2":"invalid input or unknown evidence"}}

def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def load(root):
    if not root.is_dir(): raise ValueError("receipt directory missing")
    rows={}
    paths=sorted(root.glob("*.json"))
    if len(paths)>1000: raise ValueError("receipt directory exceeds R0 bound")
    for p in paths:
        if p.is_symlink() or not p.is_file(): raise ValueError("receipt must be a regular non-symlink file")
        if p.stat().st_size>2_000_000: raise ValueError("receipt exceeds R0 size bound")
        raw=p.read_bytes(); r=json.loads(raw)
        if not isinstance(r,dict) or r.get("schema_version")!=2: raise ValueError("unsupported receipt schema")
        if (r.get("experiment") or {}).get("claim_type")!="framework-proving": raise ValueError("receipt purpose is not admitted by this framework-only viewer")
        rid=r["run_id"]; obs=r["observation"]
        if not isinstance(rid,str) or not rid or type(obs["success"]) is not bool: raise ValueError("invalid receipt fields")
        if type(obs["wall_seconds"]) not in (int,float) or not math.isfinite(obs["wall_seconds"]) or obs["wall_seconds"]<0: raise ValueError("invalid wall duration")
        if obs["termination_class"] not in ("semantic-success","semantic-failure","timeout-censored","validator-invalid","execution-error"): raise ValueError("unknown termination class")
        if obs["success"]!=(obs["termination_class"]=="semantic-success"): raise ValueError("inconsistent acceptance and termination")
        d="sha256:"+hashlib.sha256(raw).hexdigest()
        row={"run_id":rid,"task":r["task"]["id"],"candidate":r["candidate"]["harness"]["name"],"accepted":obs["success"],"termination":obs["termination_class"],"wall_seconds":obs["wall_seconds"],"receipt_sha256":d,"purpose":"FRAMEWORK_PROVING_ONLY","promotion":"NOT_AUTHORIZED"}
        if rid in rows and rows[rid]!=row: raise ValueError("divergent duplicate run_id")
        rows[rid]=row
    result=sorted(rows.values(),key=lambda x:x["run_id"])
    return {"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","runs":result,"summary":{"total":len(result),"accepted":sum(x["accepted"] for x in result),"not_accepted":sum(not x["accepted"] for x in result)}}
def main():
    p=argparse.ArgumentParser(description="Read-only qualification evidence workbench")
    p.add_argument("command",choices=CAPABILITIES["commands"])
    p.add_argument("--receipts",type=Path)
    p.add_argument("--run-id")
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    try:
        if a.command=="discover": result=CAPABILITIES
        else:
            if not a.receipts: raise ValueError("--receipts required")
            result=load(a.receipts)
            if a.command=="evidence":
                result=next((x for x in result["runs"] if x["run_id"]==a.run_id),None)
                if result is None: raise ValueError("run_id not found")
            if a.command=="render":
                if not a.output: raise ValueError("--output required")
                # Escape script termination; render values using textContent, never HTML.
                data=canonical(result).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
                template=(ROOT/"view.html").read_text(encoding="utf-8")
                with a.output.open("x",encoding="utf-8") as f: f.write(template.replace("__SNAPSHOT__",data))
                result={"output":str(a.output),"scope":result["scope"],"summary":result["summary"]}
        print(canonical(result))
        return 0
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as e:
        print(canonical({"error":"INVALID_INPUT","detail":str(e)}),file=sys.stderr)
        return 2
if __name__=="__main__": sys.exit(main())
