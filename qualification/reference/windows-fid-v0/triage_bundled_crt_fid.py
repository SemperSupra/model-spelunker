#!/usr/bin/env python3
"""W-4 *calibration* policy for bundled Visual Studio FID candidates.

No FID score is a probability. The production-side /MAP linker oracle is
validator-only. Candidate output for a reversing actor must NEVER include this
oracle or identities of excluded candidates. It only accepts observed
best-score uniqueness and provenance-qualified held-out evidence.
"""
from __future__ import annotations
import argparse, json, sys
from collections import Counter
from pathlib import Path

def assess(record:dict) -> dict:
    if record.get("schema_version") != 1 or "evaluated" not in record:
        raise ValueError("unsupported historical receipt")
    outcome={}
    for flavor in ("static","dynamic"):
        section=record["evaluated"][flavor]
        candidates=section["bounded_candidates"]
        if len(candidates)>60 or len(candidates)>section["fid_matches"]:
            raise ValueError("bounded candidate array inconsistent with receipt")
        addresses=[x["address"] for x in candidates]
        if len(addresses)!=len(set(addresses)):
            raise ValueError("duplicate candidate address in bounded projection")
        unique=[x for x in candidates if x["ties"]==1]
        tied=[x for x in candidates if x["ties"]>1]
        if len(unique)+len(tied)!=len(candidates):
            raise ValueError("unscorable tie count")
        named_exact=[x for x in unique if x["classification"]=="TP_EXACT_CRT"]
        known_errors=[x for x in unique if x["classification"]=="MISMATCH_CRT"]
        unverified=[x for x in unique if x["classification"]=="UNATTRIBUTED_OR_NONCRT"]
        if len(unique)!=len(named_exact)+len(known_errors)+len(unverified):
            raise ValueError("unknown oracle classification")
        outcome[flavor]={
            "bounded_rows":len(candidates),
            "unambiguous":len(unique),
            "ambiguous_abstentions":len(tied),
            "exact_unique_calibration_only":len(named_exact),
            "wrong_name_unique":len(known_errors),
            "unattributed_unique":len(unverified),
            "unobserved_rows":section["fid_matches"]-len(candidates),
            "precision_on_known_unique":round(
                len(named_exact)/(len(named_exact)+len(known_errors)),5
            ) if named_exact or known_errors else None,
            "auto_apply_permitted":False,
        }
    return {
        "schema_version":1,
        "status":"W4_UNIQUE_CANDIDATE_CALIBRATION_ONLY",
        "source_receipt":"GHA run 39127085635 / artifact 12136880097",
        "treatment":"bundled VS x64 FID MSVC14.51 static /MT vs dynamic /MD",
        "observed":outcome,
        "gates":{
            "production_identification":"NOT_QUALIFIED",
            "actor_tools_must_hide_source_linker_MAP":True,
            "held_out_version_and_optimizer_controls":"NOT_RUN",
            "tied_names_auto_apply":False,
            "unattributed_names_auto_apply":False,
            "correctly_named_unique_matches_sufficient_for_promotion":False,
        },
    }

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("receipt",type=Path)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    result=assess(json.loads(a.receipt.read_text()))
    print(json.dumps(result,sort_keys=True))
    if a.output:
        a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except (OSError,ValueError,KeyError,TypeError,ZeroDivisionError) as ex:
        print("W4_CALIBRATION_FAIL="+str(ex),file=sys.stderr)
        sys.exit(1)
