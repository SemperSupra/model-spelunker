#!/usr/bin/env python3
"""W-5a producer-only release vs debug MSVC CRT implementation/config oracle.

Fail closed if debug CRT not linked, PE ABI wrong, or provenance indistinguishable.
No vendor bytes, linker maps, object data, debug/private metadata are published.
"""
import argparse, hashlib, json, re, struct
from pathlib import Path
from verify_msvc import pe_identity

MAP_RE = re.compile(r"(?i)\b((?:libcmt|libucrt|libvcruntime|libcmtd|libucrtd|libvcruntimed)):[\w.$-]+\.obj\b")
DEBUG={"libcmtd","libucrtd","libvcruntimed"}
RELEASE={"libcmt","libucrt","libvcruntime"}

def text(p,limit=12_000_000):
    if not p.is_file() or not 0<p.stat().st_size<=limit:raise ValueError("missing/oversize producer diagnostic: "+p.name)
    return p.read_text(encoding="utf-8",errors="replace")

def code_section(path):
    data=path.read_bytes()
    if len(data)<256 or data[:2]!=b"MZ":raise ValueError("not a PE")
    at=struct.unpack_from("<I",data,0x3c)[0]
    if at+24>len(data) or data[at:at+4]!=b"PE\0\0":raise ValueError("invalid PE")
    n=struct.unpack_from("<H",data,at+6)[0]
    opt=struct.unpack_from("<H",data,at+20)[0]
    s=at+24+opt
    if n<1 or n>96 or s+n*40>len(data):raise ValueError("invalid PE sections")
    chunks=[]
    for i in range(n):
        o=s+40*i
        name=data[o:o+8].split(b"\0")[0]
        size,ptr=struct.unpack_from("<II",data,o+16)
        if name==b".text":
            if size<1 or ptr>len(data)-size:raise ValueError("invalid .text")
            chunks.append(data[ptr:ptr+size])
    if len(chunks)!=1:raise ValueError("missing or duplicate .text")
    return hashlib.sha256(chunks[0]).hexdigest(),len(chunks[0])

def evaluate(root):
    release,debug=root/"crt_static.exe",root/"crt_debug.exe"
    if pe_identity(release)["format"]!="PE32+ x64" or pe_identity(debug)["format"]!="PE32+ x64":
        raise ValueError("wrong PE architecture")
    rel_map,dbg_map=text(root/"crt_static.map"),text(root/"crt_debug.map")
    release_refs={m.lower() for m in MAP_RE.findall(rel_map)}
    debug_refs={m.lower() for m in MAP_RE.findall(dbg_map)}
    if not {"libcmt","libucrt"} <= release_refs:
        raise ValueError("reference not real release static CRT")
    if not {"libcmtd","libucrtd"} <= debug_refs:
        raise ValueError("actual debug code-bearing CRT not found in linker MAP")
    if debug_refs & RELEASE or release_refs & DEBUG:
        raise ValueError("cross-contamination of debug/release static CRT")
    if "qsort" in text(root/"crt_debug-imports.txt").lower():
        raise ValueError("debug CRT qsort unexpectedly imported")
    rel_hash,rel_size=code_section(release)
    dbg_hash,dbg_size=code_section(debug)
    if rel_hash==dbg_hash:raise ValueError("debug/release linked code identical")
    return {"schema":1,"status":"W5_NATIVE_DEBUG_CRT_PROVENANCE_PASS",
       "baseline":"MSVC /O2 /MT","treatment":"MSVC /O2 /MTd",
       "release_crt_library_labels":sorted(release_refs),
       "debug_crt_library_labels":sorted(debug_refs),
       "release_text_sha256":rel_hash,"debug_text_sha256":dbg_hash,
       "release_text_bytes":rel_size,"debug_text_bytes":dbg_size,
       "distinct_linked_crt_family":True,"same_author_owned_consumer":True,
       "pe_executed":False,"vendor_bytes_uploaded":False,
       "auto_naming_permitted":False,"actor_qualified":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    a=p.parse_args()
    x=evaluate(a.root)
    (a.root/"w5-debug-crt-preflight.json").write_text(json.dumps(x,indent=2,sort_keys=True)+"\n")
    print("W5_DEBUG_CRT_PREFLIGHT="+json.dumps(x,sort_keys=True))

if __name__=="__main__":main()
