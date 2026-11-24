"""Conditional configuration library vs exhaustive independent finite oracle.
All components are fictional labels; no live capability or authority admission.
"""
import itertools, json, hashlib, pathlib, sys
import numpy as np
from ConfigSpace import ConfigurationSpace, Configuration, Categorical, EqualsCondition, ForbiddenAndConjunction, ForbiddenEqualsClause

def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"))
def expected(x):
    if set(x)-{"engine","context","memory","retrieval","cache_precision","parallel","tool_projection"}: return False
    if not {"engine","context","memory","parallel","tool_projection"}<=set(x): return False
    if x["engine"] not in ("cpu","gpu") or x["context"] not in ("native","coordinated") or x["memory"] not in ("off","on") or x["parallel"] not in (1,2) or x["tool_projection"] not in ("native","compact"): return False
    if ("retrieval" in x)!=(x["memory"]=="on"): return False
    if "retrieval" in x and x["retrieval"] not in (2,4): return False
    if ("cache_precision" in x)!=(x["engine"]=="gpu"): return False
    if "cache_precision" in x and x["cache_precision"] not in ("fp16","q8"): return False
    if x["engine"]=="cpu" and x["parallel"]==2: return False
    if x["memory"]=="on" and x["context"]=="native": return False
    return True
def make_space():
    cs=ConfigurationSpace(seed=19)
    engine=Categorical("engine",["cpu","gpu"],default="cpu")
    context=Categorical("context",["native","coordinated"],default="native")
    memory=Categorical("memory",["off","on"],default="off")
    retrieval=Categorical("retrieval",[2,4])
    cache=Categorical("cache_precision",["fp16","q8"])
    parallel=Categorical("parallel",[1,2],default=1)
    tools=Categorical("tool_projection",["native","compact"],default="native")
    cs.add([engine,context,memory,retrieval,cache,parallel,tools])
    cs.add([EqualsCondition(retrieval,memory,"on"),EqualsCondition(cache,engine,"gpu")])
    cs.add([ForbiddenAndConjunction(ForbiddenEqualsClause(engine,"cpu"),ForbiddenEqualsClause(parallel,2)),ForbiddenAndConjunction(ForbiddenEqualsClause(memory,"on"),ForbiddenEqualsClause(context,"native"))])
    return cs
def native_valid(cs,x):
    try:
        c=Configuration(cs,values=x)
        c.check_valid_configuration()
        return True
    except (ValueError,TypeError,KeyError): return False
def main():
    out=pathlib.Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    cs=make_space()
    names=["engine","context","memory","retrieval","cache_precision","parallel","tool_projection"]
    levels=[["cpu","gpu"],["native","coordinated"],["off","on"],[None,2,4],[None,"fp16","q8"],[1,2],["native","compact"]]
    space=[{k:v for k,v in zip(names,vals) if v is not None} for vals in itertools.product(*levels)]
    valid=[];invalid=[]
    for x in space:
        want=expected(x)
        actual=native_valid(cs,x)
        assert actual==want, (x,want,actual)
        (valid if want else invalid).append(x)
    samples=[{k:(v.item() if isinstance(v,np.generic) else v) for k,v in dict(c).items()} for c in cs.sample_configuration(256)]
    assert all(expected(x) for x in samples)
    # Unknown keys, inactive fields and unknown value are explicitly rejected.
    default=dict(cs.get_default_configuration())
    negatives=[{**default,"unknown":"x"},{**default,"retrieval":2},{**default,"engine":"bad"}]
    assert all(not native_valid(cs,x) and not expected(x) for x in negatives)
    receipt={"scope":"FRAMEWORK_PROVING_ONLY","upstream":"74ddd4c286531778532d5fad5b79c4a1dbded2c5","factors":len(names),"enumerated":len(space),"valid":len(valid),"invalid":len(invalid),"native_oracle_agreement":len(space),"valid_samples":len(samples),"unique_samples":len({canonical(x) for x in samples}),"negative_controls":len(negatives),"valid_manifest_sha256":hashlib.sha256(canonical(valid).encode()).hexdigest(),"status":"PASS"}
    for name,payload in [("receipt.json",receipt),("valid-configurations.json",valid)]:
        (out/name).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("CONDITIONAL_DOE="+json.dumps(receipt),flush=True)
if __name__=="__main__": main()
