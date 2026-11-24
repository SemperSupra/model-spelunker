"""Strict R0 resource-sidecar projection. No independent qualification or new collector."""
import json,math
from pathlib import Path
SCOPE="canonical runner and waited child processes; excludes runner provisioning and remote processes"
UNITS={"cpu_seconds":"cpu-s","wall_seconds":"s","peak_child_rss_bytes":"B","gpu_seconds":"gpu-s","energy_joules":"J","prefill_seconds":"s","decode_seconds":"s"}
def attach(result,folder):
    if not folder.is_dir():raise ValueError("resource directory missing")
    paths=sorted(folder.glob("*.json"))
    if len(paths)>1000:raise ValueError("resource directory exceeds bound")
    lookup={r["run_id"]:r for r in result["runs"]}
    seen=set()
    for p in paths:
        if p.is_symlink() or not p.is_file() or p.stat().st_size>2_000_000:raise ValueError("invalid resource file")
        s=json.loads(p.read_bytes())
        if s["schema_version"]!=1 or s["scope"]!="FRAMEWORK_PROVING_ONLY" or s["accounting_scope"]!=SCOPE:raise ValueError("resource scope mismatch")
        rid=s["run_id"];r=lookup.get(rid)
        if r is None or rid in seen or s["receipt_sha256"]!=r["receipt_sha256"] or s["accepted"] is not r["accepted"]:raise ValueError("resource binding or duplicate mismatch")
        seen.add(rid)
        if set(s["metrics"])!=set(UNITS):raise ValueError("metric keys mismatch")
        for k,m in s["metrics"].items():
            if m["unit"]!=UNITS[k] or not isinstance(m["source"],str) or not m["source"]:raise ValueError("metric source or unit mismatch")
            val=m["value"]
            if m["status"]=="UNKNOWN":
                if val is not None:raise ValueError("unknown numeric measurement")
            elif m["status"]!="OBSERVED" or type(val) not in (int,float) or not math.isfinite(val) or val<0:raise ValueError("invalid observation")
            if k in ("gpu_seconds","energy_joules","prefill_seconds","decode_seconds") and m["status"]!="UNKNOWN":raise ValueError("R0 sensor does not observe this metric")
        r["resources"]=s["metrics"]
    n=len(lookup);accepted=result["summary"]["accepted"]
    vals=[r["resources"]["cpu_seconds"]["value"] for r in lookup.values() if "resources" in r]
    complete=n>0 and len(seen)==n and all(x is not None for x in vals)
    cpu=sum(vals) if complete else None
    result["resources"]={"total":n,"covered":len(seen),"cpu_coverage":sum(x is not None for x in vals),"cpu_seconds":cpu,"cpu_seconds_per_accepted":cpu/accepted if cpu is not None and accepted else None,"accounting_scope":SCOPE,"gpu_seconds":None,"energy_joules":None}
