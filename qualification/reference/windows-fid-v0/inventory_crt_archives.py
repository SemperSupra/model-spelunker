#!/usr/bin/env python3
"""Windows x64 CRT .lib provenance: inspect member COFF headers, not filename guesses.

No vendor archive contents are published. Bounded aggregate only.
"""
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path

MAX_ARCHIVE = 100_000_000

def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as file:
        for chunk in iter(lambda: file.read(1048576), b""): h.update(chunk)
    return h.hexdigest()

def is_code_object(data: memoryview):
    if len(data) < 20: return False
    machine, nsects, opt_size = struct.unpack_from("<HH", data, 0)[0], struct.unpack_from("<H",data,2)[0], struct.unpack_from("<H",data,16)[0]
    offset=20+opt_size
    if machine == 0 and nsects == 0xFFFF and len(data) >= 56:
        # ANON_OBJECT_HEADER_BIGOBJ and short IMPORT_OBJECT_HEADER share 0/ffff.
        # Bigobj has a 16-byte class identifier and section count at byte 44.
        nsects=struct.unpack_from("<I",data,44)[0]
        machine=struct.unpack_from("<H",data,6)[0]
        offset=56
    if machine not in (0x8664,0x14c,0xaa64) or not 1<=nsects<=2048:
        return False
    if offset+nsects*40 > len(data): return False
    for i in range(nsects):
        p=offset+i*40
        name=bytes(data[p:p+8]).rstrip(b"\x00")
        raw_size=struct.unpack_from("<I",data,p+16)[0]
        flags=struct.unpack_from("<I",data,p+36)[0]
        if name.startswith(b".text") and raw_size>0 and flags&0x20:
            return True
    return False

def inspect(path: Path):
    if not path.is_file():
        return {"status":"NOT_INSTALLED"}
    size=path.stat().st_size
    if size<8 or size>MAX_ARCHIVE: raise ValueError("archive outside admitted size")
    data=memoryview(path.read_bytes())
    if bytes(data[:8]) != b"!<arch>\n": raise ValueError("missing COFF ar signature")
    pos=8
    members=0
    code=0
    names=[]
    while pos<len(data):
        if pos+60>len(data): raise ValueError("truncated archive header")
        hdr=data[pos:pos+60]
        if bytes(hdr[58:60])!=b"\x60\x0a": raise ValueError("invalid archive member header")
        try: raw_size=int(bytes(hdr[48:58]).strip())
        except ValueError as ex: raise ValueError("invalid archive size") from ex
        end=pos+60+raw_size
        if raw_size<0 or end>len(data): raise ValueError("truncated member")
        member=data[pos+60:end]
        name=bytes(hdr[:16]).decode("latin-1").strip().rstrip("/")
        members+=1
        if is_code_object(member):
            code+=1
            if len(names)<10: names.append(name)
        if members>150000: raise ValueError("too many members")
        pos=end+(raw_size&1)
    return {"status":"INVENTORIED","bytes":size,"sha256":digest(path),
            "members":members,"code_bearing_coff_members":code,
            "code_member_name_samples":names,
            "noncode_or_unparsed_members":members-code}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--vc-lib",type=Path,required=True)
    p.add_argument("--ucrt-lib",type=Path,required=True)
    p.add_argument("--um-lib",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    candidates=[("msvc/libcmt",a.vc_lib/"libcmt.lib"),
                ("msvc/libvcruntime",a.vc_lib/"libvcruntime.lib"),
                ("msvc/libcpmt",a.vc_lib/"libcpmt.lib"),
                ("msvc/msvcrt_import",a.vc_lib/"msvcrt.lib"),
                ("msvc/vcruntime_import",a.vc_lib/"vcruntime.lib"),
                ("ucrt/libucrt",a.ucrt_lib/"libucrt.lib"),
                ("ucrt/ucrt_import",a.ucrt_lib/"ucrt.lib"),
                ("winsdk/kernel32_import",a.um_lib/"kernel32.lib")]
    entries={k:inspect(path) for k,path in candidates}
    positives={k:v for k,v in entries.items() if v["status"]=="INVENTORIED" and v["code_bearing_coff_members"]>0}
    if not positives or "msvc/libcmt" not in positives:
        raise ValueError("reference libcmt archive has no observed code-bearing COFF member")
    receipt={"schema_version":1,"status":"CRT_ARCHIVE_CODE_CENSUS_PASS",
             "classification":"COFF_SECTION_BASED_NOT_SIGNATURE_MATCH",
             "producer":"preinstalled Visual Studio and Windows SDK",
             "archives":entries,"code_archive_count":len(positives),
             "vendor_archives_uploaded":False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":receipt["status"],"code_archive_count":len(positives),
                      "summaries":{k:{"members":v.get("members",0),"code":v.get("code_bearing_coff_members",0),
                                     "status":v["status"]} for k,v in entries.items()}},sort_keys=True))
if __name__=="__main__": main()
