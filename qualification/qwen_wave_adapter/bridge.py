#!/usr/bin/env python3
"""One-way typed bridge to pre-existing SupraGoFlow Go batch-wave/v1 compiler.

No scheduling/wave selection logic, network, executor, signed admission or
credential access here. Public-safe READY tasks only; refuse if >2 candidates
or private/site admission. Go batch-wave remains the only wave planner.
"""
import argparse
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"qwen_batches"))
from contract import validate


def convert(doc):
    validate(doc)
    ready=[t for t in doc["tasks"] if t["state"]=="READY"]
    if len(ready)==0:
        return {"schema":"qwen-go-wave-adapter/v1",
                "state":"NO_READY_PUBLIC_TASKS",
                "dispatch_authorized":False,
                "cards":0}
    if len(ready)>2 or len(ready)>doc["max_parallel"]:
        raise ValueError("more ready packets than externally budgeted wave; no implicit selection")
    cards=[]
    for t in ready:
        if t["runtime"]!="public-gha" or t["classification"] not in ("PUBLIC_SOURCE","SYNTHETIC"):
            raise ValueError("private or external admission cannot become public Go wave")
        if t["depends_on"] and any(next(x for x in doc["tasks"] if x["id"]==d)["state"]!="DONE_VERIFIED"
                                 for d in t["depends_on"]):
            raise ValueError("unverified dependency")
        id_=t["id"].lower()
        scope=[s.rstrip("/") for s in t["scope"]]
        if len(scope)!=len(set(scope)):
            raise ValueError("duplicate source scope")
        cards.append({
            "id":id_,"workset":t["dle"],
            "branch":"agent/issue-238-"+id_,
            "commit":t["source_sha"],
            "actor":"web-agent/qwen-"+id_,
            "venue":"public-gha","data_class":"public-safe",
            "effect":"synthetic" if t["classification"]=="SYNTHETIC" else "source",
            "depends":[],
            "reads":["qualification/qwen_batches/workset.public.json"]+
                     ["qualification/receipts/"+d.lower()+".json" for d in t["depends_on"]],
            "writes":scope+["qualification/receipts/"+id_+".json"],
            "resources":["runner/"+id_],
            "steps":["Read the current authoritative issue/AGENTS",
                     "Verify exact source SHA and owned scope",
                     "Execute only the public-safe synthetic/source check",
                     "Apply independent pass/fail oracle",
                     "Post bounded receipt and stop"],
            "oracle":t["oracle"],
            "rollback":"Discard disposable runner; do not mutate any private or permanent host",
            "receipt":t["dle"],
            "max_minutes":t["budget"]["wall_minutes"]
        })
    return {"schema":"batch-wave/v1",
            "wave":"qwen-public-r6",
            "authority":"https://github.com/SemperSupra/model-spelunker/issues/238",
            "cards":cards}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",default=str(HERE.parent/"qwen_batches/workset.public.json"))
    p.add_argument("--output")
    opts=p.parse_args()
    result=convert(json.loads(Path(opts.input).read_text()))
    raw=json.dumps(result,sort_keys=True,indent=2)+"\n"
    if opts.output:
        Path(opts.output).write_text(raw)
    print(raw)


if __name__=="__main__":
    main()
