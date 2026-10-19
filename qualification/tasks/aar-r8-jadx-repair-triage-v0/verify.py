#!/usr/bin/env python3
"""Independent source-known Kotlin/R8 compiler/repair triage verifier.

No mapping, model output, raw decompiled Java or external service required.
"""
from __future__ import annotations
import copy
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aar_source_known_task import bounded_json, check_refs, pointer

SOURCE_REVISION="721756d2ff725cd02a9439a9fffac28fab3b2c0a"
EXPECTED = {
    "release": ("BOUNDED_REPAIR_BEHAVIOR_MATCH","SOURCE_KNOWN_10_OF_10",
                "DISJOINT_HOLDOUT",(
                    pointer("variants","release","repair","status"),
                    pointer("variants","release","repair","behavior_vectors_matched"),
                )),
    "shrink-only": ("UNCLASSIFIED_JAVAC_FAILURE","UNKNOWN_UNCOMPILED",
                    "INSPECT_COMPILER_DIAGNOSTIC",(
                        pointer("variants","shrink-only","raw","javac_categories","unclassified_javac_diagnostic"),
                        pointer("variants","shrink-only","repair","status"),
                    )),
    "shrink-optimize": ("VISIBILITY_OVERLOAD_JAVAC_FAILURE","UNKNOWN_UNCOMPILED",
                        "COMPARE_DEX_JADX_ACCESS_OVERLOAD",(
                            pointer("variants","shrink-optimize","raw","javac_categories","visibility"),
                            pointer("variants","shrink-optimize","raw","javac_categories","wrong_overload"),
                            pointer("variants","shrink-optimize","repair","status"),
                        )),
    "rename-only": ("RENAMED_NOT_EVALUATED","UNKNOWN_NOT_EVALUATED",
                    "SEALED_POST_RECOVERY_IDENTIFIER_ADAPTER",(
                        pointer("variants","rename-only","score","status"),
                        pointer("controls","r8_mapping_fed_to_recoverer"),
                    )),
    "full-r8": ("RENAMED_NOT_EVALUATED","UNKNOWN_NOT_EVALUATED",
                "SEALED_POST_RECOVERY_IDENTIFIER_ADAPTER",(
                    pointer("variants","full-r8","score","status"),
                    pointer("controls","r8_mapping_fed_to_recoverer"),
                )),
}
GLOBAL={"generalized_recovery_proven":False,
        "r8_dex_behavior_qualified":False,
        "auto_repair_all_variants":False}

def fixture_ok(e: dict) -> bool:
    try:
        if e["schema_version"] != 1 or \
                e["source_class"]!="public-authored-kotlin-r8-jadx-compiler-triage":
            return False
        if e["source"]["source_revision"]!=SOURCE_REVISION or \
                e["source"]["ground_truth_mapping_supplied_to_actor"] is not False:
            return False
        if set(e["variants"])!=set(EXPECTED):
            return False
        v=e["variants"]
        if v["release"]["raw"]["javac_categories"] != \
                {"duplicate_definition":4,"missing_symbol":6}:
            return False
        if v["release"]["repair"]["behavior_vectors_matched"]!=10 or \
                v["release"]["repair"]["compiled"] is not True:
            return False
        if v["shrink-only"]["raw"]["javac_categories"]!= \
                {"unclassified_javac_diagnostic":1}:
            return False
        if v["shrink-optimize"]["raw"]["javac_categories"]!= \
                {"missing_symbol":2,"visibility":4,"wrong_overload":2}:
            return False
        if any(v[k]["raw"]["javac"]!="FAIL" or
               v[k]["repair"]["status"]!="REJECTED_UNSUPPORTED_PATTERN" or
               v[k]["repair"]["compiled"] is not False or
               v[k]["repair"]["behavior_vectors_matched"] is not None
               for k in ("shrink-only","shrink-optimize")):
            return False
        if any(v[k]["score"]["status"]!="NOT_EVALUATED_RENAMED_NO_ADAPTER"
               for k in ("rename-only","full-r8")):
            return False
        c=e["controls"]
        return (c["r8_transformed_dex_behavior"]=="NOT_TESTED"
                and c["raw_compile_failure_is_not_semantic_mismatch"] is True
                and c["r8_mapping_fed_to_recoverer"] is False
                and c["bounded_repair_must_not_relax_expected_counts"] is True
                and c["recovered_original_source_equivalence"]=="UNKNOWN")
    except (KeyError,ValueError,TypeError):
        return False

def good_result(e: dict) -> dict:
    cases={}
    for key,(classification,behavior,next_probe,refs) in EXPECTED.items():
        cases[key]={"classification":classification,"behavior":behavior,
                    "next_probe":next_probe,"evidence_refs":sorted(refs)}
    return {"schema_version":1,"cases":cases,"global":dict(GLOBAL)}

def check(root: Path) -> bool:
    try:
        e=bounded_json(root,"evidence.json")
        got=bounded_json(root,"triage.json")
        if not fixture_ok(e) or set(got)!={"schema_version","cases","global"}:
            return False
        if got["schema_version"]!=1 or set(got["cases"])!=set(EXPECTED):
            return False
        if got["global"]!=GLOBAL:
            return False
        expected=good_result(e)
        for key,(_,_,_,refs) in EXPECTED.items():
            row=got["cases"][key]
            known=expected["cases"][key]
            if not isinstance(row,dict) or set(row)!=set(known):
                return False
            if any(row[k]!=known[k] for k in known if k!="evidence_refs"):
                return False
            if not check_refs(e,row["evidence_refs"],refs):
                return False
        return True
    except (KeyError,TypeError,ValueError,OSError,json.JSONDecodeError):
        return False

def self_test() -> int:
    source=(Path(__file__).parent/"fixture"/"evidence.json").read_text()
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        (root/"evidence.json").write_text(source)
        e=json.loads(source)
        def try_result(row,valid):
            (root/"triage.json").write_text(json.dumps(row))
            assert check(root) is valid
        original=good_result(e)
        try_result(original,True)
        bad=copy.deepcopy(original)
        bad["cases"]["shrink-only"]["behavior"]="TEN_MISMATCHES"
        try_result(bad,False)
        bad=copy.deepcopy(original)
        bad["cases"]["shrink-optimize"]["classification"]="BOUNDED_REPAIR_BEHAVIOR_MATCH"
        try_result(bad,False)
        bad=copy.deepcopy(original)
        bad["global"]["generalized_recovery_proven"]=True
        try_result(bad,False)
        bad=copy.deepcopy(original)
        bad["cases"]["full-r8"]["next_probe"]="USE_MAPPING_IN_JADX"
        try_result(bad,False)
        bad=copy.deepcopy(original)
        bad["cases"]["shrink-optimize"]["evidence_refs"]=[
            pointer("variants","shrink-optimize","raw","javac_categories","wrong_overload")]
        try_result(bad,False)
        bad=copy.deepcopy(original)
        bad["cases"]["release"]["evidence_refs"].append(
            "https://attacker.example/secret")
        try_result(bad,False)
        bad=copy.deepcopy(original)
        bad["cases"]["release"]["evidence_refs"].append(
            "evidence.json#/variants/release/repair/~3invalid")
        try_result(bad,False)
        (root/"evidence.json").write_text(source.replace('"visibility": 4',
                                                         '"visibility": 40'))
        try_result(original,False)
    print("PASS aar-r8-jadx-repair-triage verifier / 8 negative controls")
    return 0

if __name__=="__main__":
    if len(sys.argv)==2 and sys.argv[1]=="--self-test":
        raise SystemExit(self_test())
    if len(sys.argv)!=2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
