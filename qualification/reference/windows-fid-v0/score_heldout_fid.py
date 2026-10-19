#!/usr/bin/env python3
"""W-4c prospective name-consensus scorer; MAP truth is evaluator-only.

Consumes read-only Ghidra FID output and an *independent* native MSVC linker
MAP. It never writes a Ghidra project, changes symbols, or supplies MAP to an
actor. The measured policy is observational and NOT approved for auto-naming.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

from verify_bundled_crt_fid import LINE, MATCH, TIE_CLASS, CRT
CRT_FAMILIES = set(CRT) | {"libcmtd", "libucrtd", "libvcruntimed"}

def _read(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > 12_000_000:
        raise ValueError("missing or oversized diagnostic: " + path.name)
    return path.read_text(encoding="utf-8", errors="replace")

def evaluate(mapping: str, ghidra: str, treatment: str) -> dict:
    if treatment not in {"static", "static_heldout", "debug", "dynamic"}:
        raise ValueError("unadmitted treatment")
    truth = {}
    for line in mapping.splitlines():
        m = LINE.match(line)
        if m:
            symbol, address, library, obj = m.groups()
            key = address.lower().lstrip("0") or "0"
            truth.setdefault(key, set()).add((symbol, library.lower()))
    if not truth:
        raise ValueError("no independent MAP symbols")
    def count(tag):
        vals = re.findall(r"RE_SHIPPED_FID_" + tag + r"=(\d+)(?!\d)", ghidra)
        if len(vals) != 1:
            raise ValueError("missing/duplicate Ghidra counter " + tag)
        return int(vals[0])
    matches = {}
    for m in MATCH.finditer(ghidra):
        address, name, score, family, version, variant, ties = m.groups()
        key = address.lower().lstrip("0") or "0"
        if key in matches or int(ties) < 1 or not re.fullmatch(r"\d+(?:\.\d+)?", score):
            raise ValueError("duplicate address / invalid tie or score")
        matches[key] = {"name": name, "ties": int(ties), "score": float(score), "variant": variant}
    groups = {}
    for addr, total, names, versions in TIE_CLASS.findall(ghidra):
        key = addr.lower().lstrip("0") or "0"
        if key in groups:
            raise ValueError("duplicate tie group")
        values = tuple(map(int, (total, names, versions)))
        if values[0] < 2 or not 1 <= values[1] <= values[0] or not 1 <= values[2] <= values[0]:
            raise ValueError("impossible tie group")
        groups[key] = values
    population=count("MATCH_COUNT")
    emitted=count("EMITTED_COUNT")
    truncated=count("TRUNCATED_COUNT")
    if (emitted!=len(matches) or emitted!=min(population,500)
            or truncated!=population-emitted or population<0):
        raise ValueError("match census/emission/truncation accounting failure")
    observed_ties=sum(m["ties"] > 1 for m in matches.values())
    if (observed_ties>count("AMBIGUOUS_COUNT") or
            (not truncated and observed_ties!=count("AMBIGUOUS_COUNT"))):
        raise ValueError("ambiguous counter mismatch")
    if set(groups) != {key for key, m in matches.items() if m["ties"] > 1}:
        raise ValueError("missing or extra tie classification")
    for key, g in groups.items():
        if g[0] != matches[key]["ties"]:
            raise ValueError("tie multiplicity mismatch")
    if sum(g[1] == 1 for g in groups.values()) > count("TIE_CONSENSUS"):
        raise ValueError("consensus total inconsistent")
    if sum(g[1] > 1 for g in groups.values()) > count("TIE_CONFLICT"):
        raise ValueError("conflict total inconsistent")
    if count("TIE_CONSENSUS")+count("TIE_CONFLICT")!=count("AMBIGUOUS_COUNT"):
        raise ValueError("global tie categories inconsistent")
    metrics = {"unique":0, "same_name_consensus":0, "conflicting_abstain":0,
               "unique_exact_crt":0, "unique_wrong_crt":0, "unique_unknown":0,
               "consensus_exact_crt":0, "consensus_wrong_crt":0, "consensus_unknown":0,
               "known_crt_map_symbols":sum(any(lib in CRT_FAMILIES for _,lib in symbols) for symbols in truth.values()),
               "map_alias_abstain":0}
    for key, m in matches.items():
        if m["ties"] == 1:
            label = "unique"
        elif groups[key][1] == 1:
            label = "same_name_consensus"
        else:
            metrics["conflicting_abstain"] += 1
            continue
        metrics[label] += 1
        identities = truth.get(key, set())
        crt_identities = {(sym, lib) for sym, lib in identities if lib in CRT_FAMILIES}
        # Linker MAP can retain several aliases at one address. An arbitrary
        # last-wins symbol would manufacture wrong/correct labels.
        if len(identities)>1:
            metrics["map_alias_abstain"] += 1
            verdict="unknown"
        elif len(crt_identities)!=1:
            verdict="unknown"
        else:
            sym,lib = next(iter(crt_identities))
            verdict="exact_crt" if sym == m["name"] else "wrong_crt"
        prefix = "consensus" if label == "same_name_consensus" else "unique"
        metrics[prefix + "_" + verdict] += 1
    # Pre-registered, strictly observational production-visible features.
    # No source MAP addresses, names, or truth enter the candidate predicate.
    threshold_buckets = []
    for label in ("unique", "same_name_consensus"):
        for threshold in (0, 25, 50, 100, 150, 200, 300):
            accepted = {"known_correct": 0, "known_wrong": 0, "unknown_or_alias": 0}
            for key, m in matches.items():
                kind = ("unique" if m["ties"] == 1 else
                        "same_name_consensus" if groups[key][1] == 1 else "conflicting_abstain")
                if kind != label or m["score"] < threshold:
                    continue
                identities = truth.get(key, set())
        crt_identities = {(sym, lib) for sym, lib in identities if lib in CRT_FAMILIES}
                if len(identities) != 1 or len(crt_identities)!=1:
                    accepted["unknown_or_alias"] += 1
                elif next(iter(crt_identities))[0] == m["name"]:
                    accepted["known_correct"] += 1
                else:
                    accepted["known_wrong"] += 1
            threshold_buckets.append({"class": label, "minimum_score": threshold,
                  "observed_first_n_only": len(matches), **accepted,
                  "accepted_total": sum(accepted.values()),
                  "candidate_policy_qualified": False})
    return {"schema":1, "treatment":treatment,
            "threshold_buckets_exploratory": threshold_buckets,
            "population_match_count":population,
            "bounded_match_count":len(matches),
            "excluded_from_sample":truncated,
            "sample_not_generalizable":bool(truncated),
            "metrics":metrics,
            "source_map_excluded_from_ghidra":True,
            "automatic_naming_permitted":False,
            "heldout_policy_promoted":False}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--query-log", type=Path, required=True)
    ap.add_argument("--treatment", choices=("static","static_heldout","debug","dynamic"), required=True)
    ap.add_argument("--output", type=Path, required=True)
    args=ap.parse_args()
    result=evaluate(_read(args.map), _read(args.query_log), args.treatment)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("W4C_HELDOUT=" + json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()
