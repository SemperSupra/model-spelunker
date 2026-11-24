"""Synthetic-only experiment plan preview and deterministic review.
A valid preview is not permission to execute. No execution interface exists.
"""
import argparse, hashlib, json, pathlib, sys

def digest(x):
    return "sha256:"+hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def review(intent,spec):
    issues=[]
    def issue(code,field):
        issues.append({"code":code,"field":field})
    if intent.get("schema_version")!=1 or spec.get("schema_version")!=1:
        issue("UNSUPPORTED_SCHEMA","schema_version")
    if intent.get("scope")!="FRAMEWORK_PROVING_ONLY" or spec.get("scope")!="FRAMEWORK_PROVING_ONLY":
        issue("SCOPE_DENIED","scope")
    if spec.get("intent_digest")!=digest(intent):
        issue("STALE_INTENT","intent_digest")
    if set(intent)!={"schema_version","scope","revision","objective","allowed_engines","max_trials"}:
        issue("UNKNOWN_INTENT_FIELDS","intent")
    if set(spec)!={"schema_version","scope","intent_digest","treatments","repetitions"}:
        issue("UNKNOWN_SPEC_FIELDS","spec")
    budget=intent.get("max_trials");reps=spec.get("repetitions")
    treatments=spec.get("treatments")
    allowed=intent.get("allowed_engines")
    if type(budget) is not int or budget<1 or budget>1000:
        issue("INVALID_BUDGET","max_trials")
    if type(reps) is not int or reps<1 or reps>1000:
        issue("INVALID_REPETITIONS","repetitions")
    if not isinstance(allowed,list) or not allowed or any(x not in ["cpu","gpu"] for x in allowed):
        issue("INVALID_ALLOWED_ENGINES","allowed_engines")
        allowed=[]
    if not isinstance(treatments,list) or not treatments or len(treatments)>1000:
        issue("INVALID_TREATMENTS","treatments")
        treatments=[]
    seen=set()
    for i,t in enumerate(treatments):
        field=f"treatments[{i}]"
        if not isinstance(t,dict) or set(t)!={"engine","memory","retrieval"}:
            issue("INVALID_TREATMENT",field);continue
        if t["engine"] not in allowed:
            issue("ENGINE_NOT_ALLOWED",field+".engine")
        if t["memory"] not in ["off","on"] or (t["memory"]=="off" and t["retrieval"] is not None) or (t["memory"]=="on" and (type(t["retrieval"]) is not int or t["retrieval"] not in [2,4])):
            issue("INCOMPATIBLE_TREATMENT",field+".retrieval")
        key=digest(t)
        if key in seen: issue("DUPLICATE_TREATMENT",field)
        seen.add(key)
    trials=len(treatments)*reps if type(reps) is int and reps>0 else None
    if trials is not None and type(budget) is int and trials>budget:
        issue("BUDGET_EXCEEDED","treatments/repetitions")
    return {"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","intent_digest":digest(intent),"spec_digest":digest(spec),"requested_trials":trials,"preview_status":"REJECTED" if issues else "REVIEWED_PREVIEW","findings":issues,"execution_authorized":False,"promotion_authorized":False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=["discover","review"])
    p.add_argument("--intent",type=pathlib.Path)
    p.add_argument("--spec",type=pathlib.Path)
    a=p.parse_args()
    if a.command=="discover":
        print(json.dumps({"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","commands":{"review":{"inputs":["--intent","--spec"],"side_effects":"none","outputs":"reviewed preview or typed findings","authority":"none","exit":{"0":"reviewed preview","2":"rejected or invalid"}}},"no_execution":True}))
        return 0
    try:
        i=json.loads(a.intent.read_text());s=json.loads(a.spec.read_text())
        if not isinstance(i,dict) or not isinstance(s,dict): raise ValueError("expected JSON objects")
        out=review(i,s);print(json.dumps(out,sort_keys=True))
        return 2 if out["findings"] else 0
    except (OSError,ValueError,AttributeError,TypeError) as e:
        print(json.dumps({"error":"INVALID_INPUT","detail":str(e)}),file=sys.stderr);return 2
if __name__=="__main__":sys.exit(main())
