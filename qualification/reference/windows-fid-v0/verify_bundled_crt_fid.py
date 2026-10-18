#!/usr/bin/env python3
"""Independent CRT FID match truth from Microsoft /MAP, outside Ghidra.
This does not use source/PDB in FID query and does not accept guessed library
names as proof of matching. All output is capped public-safe metadata.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

LINE = re.compile(r"(?i)^\s*\w{4}:\w{8}\s+(\S+)\s+([0-9a-f]{9,16})\s+f\s+(\S+?):([\w.$-]+\.obj)\s*$")
MATCH = re.compile(r"RE_SHIPPED_FID_MATCH=([0-9a-f]+)\|([^|\r\n]+)\|([^|\r\n]+)\|([^|\r\n]+)\|([^|\r\n]+)\|([^|\r\n]+)\|(\d+)")
TIE_CLASS = re.compile(r"RE_SHIPPED_FID_TIE_GROUP=([0-9a-f]+)\|(\d+)\|(\d+)\|(\d+)")
CRT = ("libcmt", "libucrt", "libvcruntime")

def read(p: Path) -> str:
    if not p.is_file() or p.stat().st_size > 12_000_000:
        raise ValueError("missing or oversized experiment log " + p.name)
    return p.read_text(encoding="utf-8",errors="replace")

def run(root: Path) -> dict:
    findings = {}
    for flavor in ("static", "dynamic"):
        mapping=read(root/f"crt_{flavor}.map")
        diagnostic=read(root/"ghidra-fid"/f"query-{flavor}.console.log")
        source_truth={}
        for line in mapping.splitlines():
            m=LINE.match(line)
            if not m: continue
            symbol,address,lib,obj=m.groups()
            address=address.lower().lstrip("0") or "0"
            source_truth[address]={"symbol":symbol,"library":lib,"object":obj}
        if not source_truth:
            raise ValueError("no source-known map truth")
        def tagged(k):
            m=re.findall(r"RE_SHIPPED_FID_"+re.escape(k)+r"=(\d+)",diagnostic)
            if len(m)!=1: raise ValueError("missing/duplicate tool count "+k)
            return int(m[0])
        analyzed=int(re.findall(r"RE_FID_FUNCTIONS_ANALYZED=(\d+)", diagnostic)[-1])
        eligible=tagged("ELIGIBLE_COUNT")
        observed=tagged("MATCH_COUNT")
        ambiguous=tagged("AMBIGUOUS_COUNT")
        entries=[]
        for m in MATCH.finditer(diagnostic):
            address,name,score,family,version,variant,ties=m.groups()
            source=source_truth.get(address.lstrip("0") or "0")
            is_crt=source is not None and source["library"].lower() in CRT
            exact=is_crt and name==source["symbol"]
            verdict=("TP_EXACT_CRT" if exact else
                     "MISMATCH_CRT" if is_crt else
                     "UNATTRIBUTED_OR_NONCRT")
            entries.append({"address":address,"candidate":name,
                            "score":float(score),"family":family,
                            "version":version,"ties":int(ties),"classification":verdict,
                            "linker_truth":source})
        if observed != len(entries) or observed > analyzed or eligible<1:
            raise ValueError("FID candidate count incompatible with analyzed functions or no eligible DB")
        tie_groups={}
        for a,count,names,versions in TIE_CLASS.findall(diagnostic):
            if a in tie_groups:raise ValueError("duplicate tie-group entry")
            count,names,versions=map(int,(count,names,versions))
            if count <= 1 or not 1 <= names <= count or not 1 <= versions <= count:
                raise ValueError("invalid tie group cardinality")
            tie_groups[a]=(count,names,versions)
        tied={e["address"]:e for e in entries if e["ties"]>1}
        if set(tie_groups)!=set(tied):
            raise ValueError("tied addresses and tie-group projection disagree")
        for address,e in tied.items():
            if tie_groups[address][0]!=e["ties"]:
                raise ValueError("tie-group count differs from candidate receipt")
        consensus=sum(v[1]==1 for v in tie_groups.values())
        conflicts=sum(v[1]>1 for v in tie_groups.values())
        def tie_stat(name):
            found=re.findall(r"RE_SHIPPED_FID_"+name+r"=(\d+)",diagnostic)
            if len(found)!=1:return None
            return int(found[0])
        if tie_stat("TIE_CONSENSUS")!=consensus or tie_stat("TIE_CONFLICT")!=conflicts:
            raise ValueError("tie category totals inconsistent")
        consensus_crt_exact=sum(e["classification"]=="TP_EXACT_CRT" for e in entries
                                if e["address"] in tie_groups and
                                tie_groups[e["address"]][1]==1)
        conflict_crt_error=sum(e["classification"]=="MISMATCH_CRT" for e in entries
                               if e["address"] in tie_groups and
                               tie_groups[e["address"]][1]>1)
        known=sum(v["library"].lower() in CRT for v in source_truth.values())
        tp=sum(x["classification"]=="TP_EXACT_CRT" for x in entries)
        wrong=sum(x["classification"]=="MISMATCH_CRT" for x in entries)
        unattributed=sum(x["classification"]=="UNATTRIBUTED_OR_NONCRT" for x in entries)
        findings[flavor]={"target_functions_analyzed":analyzed,
                          "linker_map_named_symbols":len(source_truth),
                          "known_crt_map_symbols":known,
                          "eligible_bundled_databases":eligible,
                          "fid_matches":observed,
                          "exact_crt_matches":tp,
                          "wrong_name_on_crt_address":wrong,
                          "non_crt_or_unattributed_candidates":unattributed,
                          "ambiguous_matches":ambiguous,
                          "tie_consensus_name_groups":consensus,
                          "tie_conflicting_name_groups":conflicts,
                          "tie_consensus_exact_crt_names_calibration":consensus_crt_exact,
                          "tie_conflict_wrong_crt_name_calibration":conflict_crt_error,
                          "tie_equivalence_classes": [
                            {"address":k,"total_records":v[0],"distinct_names":v[1],
                             "distinct_library_variants":v[2]}
                            for k,v in list(tie_groups.items())[:100]],
                          "bounded_candidates":entries[:60]}
    if findings["static"]["known_crt_map_symbols"]<=findings["dynamic"]["known_crt_map_symbols"]:
        raise ValueError("/MT had no higher CRT-code provenance than /MD")
    return {"schema_version":1,
            "status":"BUNDLED_FID_COMPARISON_RECORDED_NOT_ASSERTED_SUCCESS",
            "tool":"Ghidra 12.1.4 bundled FID only",
            "evaluated":findings,"pe_executed":False,
            "binary_or_sdk_bytes_uploaded":False,
            "actor_qualified":False}

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    a=p.parse_args()
    try:
        result=run(a.root)
        out=a.root/"ghidra-bundled-fid-evaluation.json"
        out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
        for flavor,val in result["evaluated"].items():
            print("RE_SHIPPED_CRT_EVALUATION="+json.dumps({"flavor":flavor,
                **{k:v for k,v in val.items() if k!="bounded_candidates"}},sort_keys=True))
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print("RE_SHIPPED_CRT_ORACLE_FAIL="+str(exc),file=sys.stderr)
        sys.exit(1)
