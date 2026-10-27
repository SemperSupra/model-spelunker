#!/usr/bin/env python3
"""Independent source-known /MT vs /MD real MSVC CRT library provenance oracle."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from verify_msvc import pe_identity

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def text(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > 6_000_000:
        raise ValueError("missing/oversized bounded diagnostic " + path.name)
    return path.read_text(encoding="utf-8", errors="replace")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    args=ap.parse_args()
    root=args.root
    files={}
    for flavor in ("static","dynamic"):
        exe=root/("crt_"+flavor+".exe")
        imp=text(root/("crt_"+flavor+"-imports.txt"))
        dep=text(root/("crt_"+flavor+"-dependents.txt"))
        log=text(root/("crt_"+flavor+"-link.log"))
        mapping=text(root/("crt_"+flavor+".map"))
        ident=pe_identity(exe)
        files[flavor]={
            **ident, "dll_dependencies":sorted(set(re.findall(r"(?im)^\s+([\w.-]+\.dll)\s*$",dep))),
            "qsort_imported":bool(re.search(r"\bqsort\b",imp)),
            "strtoui64_imported":bool(re.search(r"\b_strtoui64\b",imp)),
            "linked_libs":sorted(set(re.findall(r"(?i)\b((?:libucrt|libcmt|libvcruntime|ucrt|vcruntime|msvcrt)\.lib)\b",log))),
            # MSVC 14.51 /MAP provenance: "LIBCMT:utility.obj" or "libucrt:argv_data.obj".
            # Modern /VERBOSE:LIB may emit Searching only; do not infer member inclusion from it.
            "linked_crt_member_references":len(set(re.findall(
                r"(?i)\b(?:libucrt|libcmt|libvcruntime):[\w.$-]+\.obj\b", mapping))),
            "has_static_ucrt_map_member":bool(re.search(r"(?i)\blibucrt:[\w.$-]+\.obj\b",mapping)),
            "has_static_msvc_crt_map_member":bool(re.search(r"(?i)\bLIBCMT:[\w.$-]+\.obj\b",mapping)),
            "link_log_sha256":sha(root/("crt_"+flavor+"-link.log")),
            "map_sha256":sha(root/("crt_"+flavor+".map")),
            "map_mentions_export":("re_crt_dispatch" in mapping),
        }
    a,b=files["static"],files["dynamic"]
    if a["sha256"]==b["sha256"]:
        raise ValueError("static and dynamic PE equal")
    if a["qsort_imported"] or not b["qsort_imported"]:
        raise ValueError("expected qsort statically resolved only for /MT")
    if not a["has_static_ucrt_map_member"] or not a["has_static_msvc_crt_map_member"]:
        raise ValueError("static /MT MAP lacks actual UCRT and MSVC CRT member attribution")
    if a["linked_crt_member_references"] < 2:
        raise ValueError("insufficient archive-member provenance in static PE map")
    if not a["map_mentions_export"] or not b["map_mentions_export"]:
        raise ValueError("source-known exported function absent in map")
    receipt={"schema_version":1,"status":"NATIVE_MSVC_STATIC_VS_DYNAMIC_CRT_PROVENANCE_PASS",
             "source_sha256":sha(Path(__file__).with_name("windows_crt_consumer.c")),
             "producer":"installed Microsoft cl.exe/link.exe, /MT compared with /MD",
             "files":files,"experiment":"CRT_PROVENANCE_ONLY_NOT_FID_MATCH",
             "executables_run":False,"vendor_libraries_uploaded":False}
    (root/"crt-linkage-receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"status":receipt["status"],"summary":{k:{
        "size":v["size"],"qsort_imported":v["qsort_imported"],
        "linked_crt_member_references":v["linked_crt_member_references"],
        "dll_dependencies":v["dll_dependencies"],
        "linked_libs":v["linked_libs"]} for k,v in files.items()}},sort_keys=True))

if __name__=="__main__": main()
