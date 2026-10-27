#!/usr/bin/env python3
"""W-4c independent COFF machine-code distinctness gate for /O1 vs /O2.

Names and reference source are never supplied to Ghidra. This producer-side
oracle fingerprints only author-owned COFF code sections. It explicitly
rejects metadata-only differences as proof of an optimizer treatment.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

def code_sections(path):
    data=Path(path).read_bytes()
    if len(data)<60 or struct.unpack_from("<H",data)[0]!=0x8664:
        raise ValueError("not ordinary x64 COFF")
    n=struct.unpack_from("<H",data,2)[0]
    optional=struct.unpack_from("<H",data,16)[0]
    pos=20+optional
    if not 1<=n<=256 or pos+n*40>len(data):
        raise ValueError("invalid COFF section table")
    rows=[]
    for i in range(n):
        o=pos+i*40
        name=data[o:o+8].split(b"\0",1)[0].decode("ascii","replace")
        size,ptr=struct.unpack_from("<II",data,o+16)
        flags=struct.unpack_from("<I",data,o+36)[0]
        if not flags&0x20: continue
        if not size or size>len(data) or ptr>len(data)-size:
            raise ValueError("malformed populated code section")
        rows.append((name,data[ptr:ptr+size]))
    if not rows:raise ValueError("missing author-owned code sections")
    return rows

def fingerprint(path):
    rows=code_sections(path)
    h=hashlib.sha256()
    for name,raw in rows:
        h.update(len(raw).to_bytes(8,"little"))
        h.update(raw)
    return {"code_sha256":h.hexdigest(),"code_sections":len(rows),
            "code_bytes":sum(len(raw) for _,raw in rows)}

def verify(root):
    a=fingerprint(root/"crt_static.obj")
    b=fingerprint(root/"crt_static_heldout.obj")
    result={"schema":1,"baseline_flags":"/O2 /MT","heldout_flags":"/O1 /MT",
        "baseline":a,"heldout":b,"compiled_code_distinct":a["code_sha256"]!=b["code_sha256"],
        "meaningful_optimizer_holdout_verified":a["code_sha256"]!=b["code_sha256"],
        "metadata_only_difference_not_accepted":True,"auto_name_permitted":False}
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    a=ap.parse_args()
    result=verify(a.root)
    (a.root/"w4c-optimizer-fingerprint.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("W4C_OPTIMIZER_FINGERPRINT="+json.dumps(result,sort_keys=True))
if __name__=="__main__":
    main()
