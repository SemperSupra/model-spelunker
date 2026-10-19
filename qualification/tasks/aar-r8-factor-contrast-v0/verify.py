#!/usr/bin/env python3
"""Sealed verifier: source-known nested R8 factor comparison, no semantics promotion."""
from __future__ import annotations
import copy
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aar_source_known_task import bounded_json, check_refs, pointer

PAIRS = {
    "rename-vs-release": ("release","rename-only","RENAMING_NO_SHRINK_SMALLER"),
    "shrink-vs-release": ("release","shrink-only","SHRINK_ENABLED_MUCH_FEWER"),
    "optimize-given-shrink": ("shrink-only","shrink-optimize","OPTIMIZE_AFTER_SHRINK_FEWER"),
    "rename-given-shrink-and-optimize": ("shrink-optimize","full-r8",
                                        "RENAME_AFTER_OPTIMIZE_MORE")
}
KNOWN_FILES = {"release":688,"rename-only":667,"shrink-only":67,
               "shrink-optimize":39,"full-r8":44}
KNOWN_EXITS = {"release":3,"rename-only":3,"shrink-only":0,
               "shrink-optimize":0,"full-r8":0}
SOURCE_REVISION="721756d2ff725cd02a9439a9fffac28fab3b2c0a"

def fixture_ok(doc: dict) -> bool:
    try:
        if doc["schema_version"] != 1 or doc["source_class"] != \
                "public-authored-kotlin-r8-golden-observations":
            return False
        src=doc["source"]
        if src["source_revision"] != SOURCE_REVISION or \
                src["mapping_disclosed_to_actor"] is not False:
            return False
        if set(doc["profiles"]) != set(KNOWN_FILES):
            return False
        if any(type(doc["profiles"][k]["java_files"]) is not int or
               doc["profiles"][k]["java_files"] != count or
               doc["profiles"][k]["jadx_exit"] != KNOWN_EXITS[k]
               for k,count in KNOWN_FILES.items()):
            return False
        c=doc["controls"]
        return (c["r8_flags_are_not_orthogonal"] is True
                and c["dontshrink_also_restricts_optimization"] is True
                and c["r8_dex_behavior_equivalence"]=="NOT_TESTED"
                and c["original_source_identifiers"]=="NOT_OBSERVABLE_BLIND"
                and c["file_count_is_not_recovery_quality"] is True)
    except (KeyError, TypeError, ValueError):
        return False

def good_result(doc: dict) -> dict:
    rows={}
    for case,(lhs,rhs,observation) in PAIRS.items():
        l,r=doc["profiles"][lhs],doc["profiles"][rhs]
        refs=sorted([pointer("profiles",lhs,"java_files"),
                     pointer("profiles",rhs,"java_files"),
                     pointer("controls","r8_flags_are_not_orthogonal")])
        rows[case]={"lhs":lhs,"rhs":rhs,
                    "delta_java_files":r["java_files"]-l["java_files"],
                    "exit_change":"SAME" if l["jadx_exit"]==r["jadx_exit"] else "CHANGED",
                    "observation":observation,"evidence_refs":refs}
    return {"schema_version":1,"comparisons":rows,
            "controls":{"independent_causal_claim":False,
                        "restored_original_source":False,
                        "proven_semantic_recovery":False}}

def check(root: Path) -> bool:
    try:
        evidence=bounded_json(root,"evidence.json")
        result=bounded_json(root,"classification.json")
        if not fixture_ok(evidence):
            return False
        expected=good_result(evidence)
        if set(result)!={"schema_version","comparisons","controls"}:
            return False
        if result["schema_version"]!=1 or set(result["comparisons"])!=set(PAIRS):
            return False
        if result["controls"]!=expected["controls"]:
            return False
        for case,(lhs,rhs,_) in PAIRS.items():
            row=result["comparisons"][case]
            wanted=expected["comparisons"][case]
            if set(row)!=set(wanted):
                return False
            if any(row[k]!=wanted[k] for k in wanted if k!="evidence_refs"):
                return False
            required=(pointer("profiles",lhs,"java_files"),
                      pointer("profiles",rhs,"java_files"),
                      pointer("controls","r8_flags_are_not_orthogonal"))
            if not check_refs(evidence,row["evidence_refs"],required):
                return False
        return True
    except (KeyError,TypeError,ValueError, OSError, json.JSONDecodeError):
        return False

def self_test() -> int:
    original=(Path(__file__).parent/"fixture"/"evidence.json").read_text()
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        (root/"evidence.json").write_text(original)
        doc=json.loads(original)
        def try_result(result, valid):
            (root/"classification.json").write_text(json.dumps(result))
            assert check(root) is valid
        result=good_result(doc)
        try_result(result,True)
        bad=copy.deepcopy(result)
        bad["comparisons"]["shrink-vs-release"]["delta_java_files"] += 1
        try_result(bad,False)
        bad=copy.deepcopy(result)
        bad["comparisons"]["shrink-vs-release"]["observation"]="RECOVERED_ORIGINAL_SOURCE"
        try_result(bad,False)
        bad=copy.deepcopy(result)
        bad["controls"]["proven_semantic_recovery"]=True
        try_result(bad,False)
        bad=copy.deepcopy(result)
        bad["comparisons"]["rename-vs-release"]["evidence_refs"]=[
            "evidence.json#/source/run_url"]
        try_result(bad,False)
        bad=copy.deepcopy(result)
        bad["comparisons"]["rename-vs-release"]["evidence_refs"].append(
            "evidence.json#/profiles/not-a-class/java_files")
        try_result(bad,False)
        bad=copy.deepcopy(result)
        bad["comparisons"]["rename-vs-release"]["evidence_refs"].append(
            "evidence.json#/controls/~xx")
        try_result(bad,False)
        (root/"evidence.json").write_text(original.replace('"java_files": 688',
                                                           '"java_files": 689'))
        try_result(result,False)
    print("PASS aar-r8-factor-contrast verifier / 7 negative controls")
    return 0

if __name__=="__main__":
    if len(sys.argv)==2 and sys.argv[1]=="--self-test":
        raise SystemExit(self_test())
    if len(sys.argv)!=2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
