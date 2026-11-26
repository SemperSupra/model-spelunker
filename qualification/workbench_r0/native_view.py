"""Read-only native phase projection, using the existing #385 binder.
Trusted synthetic bundles only; no server attestation or qualification promotion.
"""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"native_phase_task_r0"))
from prove import bind

def read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>2_000_000:
        raise ValueError("invalid native bundle file")
    return path.read_bytes()
def parse(raw):
    return json.loads(raw,parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
def attach(result,folder):
    if not folder.is_dir() or folder.is_symlink():raise ValueError("invalid native bundle directory")
    lookup={r["run_id"]:r for r in result["runs"]}
    bundles=sorted(folder.iterdir())
    if len(bundles)>1000:raise ValueError("native bundle bound exceeded")
    seen=set();requests=set()
    for d in bundles:
        if not d.is_dir() or d.is_symlink():raise ValueError("expected native bundle directory")
        raw=read(d/"receipt.json");receipt=parse(raw)
        rid=receipt["run_id"];row=lookup.get(rid)
        if row is None or rid in seen or row["receipt_sha256"]!="sha256:"+hashlib.sha256(raw).hexdigest():raise ValueError("orphan, duplicate or mismatched native receipt")
        if (d/"snapshot").is_symlink():raise ValueError("invalid snapshot directory")
        joined=bind(parse(read(d/"packet.json")),raw,parse(read(d/"phase.json")),read(d/"snapshot/value.txt"))
        # No acceptance or measured rates accepted from a precomputed projection.
        if joined["request_id"] in requests:raise ValueError("duplicate request identity")
        seen.add(rid);requests.add(joined["request_id"])
        row["native_phase"]=joined
    result["native_phase"]={"covered":len(seen),"total":len(lookup),"source_scope":"trusted public synthetic probe; not independent server attestation","cross_tokenizer_comparison":"NOT_SUPPORTED","cached_tokens":None,"reasoning_tokens":None}
