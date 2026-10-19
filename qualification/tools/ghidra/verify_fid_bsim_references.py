#!/usr/bin/env python3
"""Independent bounded smoke for a public-safe FID+H2 BSim reference build.

Measures database existence and known labels. Does not claim stripped-target matching.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    if len(sys.argv)!=2: return 2
    root=Path(sys.argv[1])
    out=root/"output"
    fid=out/"source-known.fidb"
    bsim=out/"source-known-bsim.mv.db"
    reference=root/"source_known_reference.so"
    target=root/"stripped_target.so"
    for p in (fid,bsim,reference,target):
        if not p.is_file() or p.stat().st_size<128: raise RuntimeError("missing/undersized "+str(p.name))
    if sha(reference)==sha(target): raise RuntimeError("reference and target identical")
    log=(out/"fid-stdout.log").read_text(errors="replace")
    added=re.findall(r"RE_FID_ADDED=(\d+)",log)
    if len(added)!=1 or int(added[0])<1: raise RuntimeError("FID no function ingested")
    listing=(out/"bsim-functions.log").read_text(errors="replace")
    labels=[x for x in ("handler_fold","handler_rotate","handler_affine","command_dispatch") if x in listing]
    if not labels: raise RuntimeError("BSim known function labels absent")
    record={"status":"REFERENCE_DB_CREATED","fid_added":int(added[0]),
            "bsim_known_labels":labels,"sha256":{
                "reference":sha(reference),"stripped_target":sha(target),
                "fidb":sha(fid),"bsim_h2":sha(bsim)}}
    print(json.dumps(record,sort_keys=True))
    (out/"reference-receipt.json").write_text(json.dumps(record,indent=2,sort_keys=True)+"\n")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
