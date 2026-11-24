"""Source-neutral proof of upstream DOE generation and independent screening.
No inference, deployment or operational qualification claims.
"""
import hashlib
import itertools
import json
import pathlib
import sys
import numpy as np
from pyDOE3 import fracfact

NAMES=["prompt","tool_schema","tool_result","context","memory","parallel","bypass","recovery"]
SOURCE="b4f56a5b261c7508a0d661af0b0a894eb75955e4"
GEN="a b c d abc abd acd bcd"

def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def plan():
    x=fracfact(GEN).astype(int)
    # Independent algebraic oracle (ordering is not part of upstream contract).
    known=set()
    for a,b,c,d in itertools.product((-1,1),repeat=4):
        known.add((a,b,c,d,a*b*c,a*b*d,a*c*d,b*c*d))
    assert x.shape==(16,8) and {tuple(row) for row in x}==known
    assert np.array_equal(x.T@x,np.eye(8,dtype=int)*16)
    assert np.all(x.sum(axis=0)==0)
    pairs=list(itertools.combinations(range(8),2))
    p=np.column_stack([x[:,i]*x[:,j] for i,j in pairs])
    assert np.all(x.T@p==0)
    aliases={}
    for k,(i,j) in enumerate(pairs):
        name=NAMES[i]+"*"+NAMES[j]
        aliases[name]=[NAMES[u]+"*"+NAMES[v] for l,(u,v) in enumerate(pairs) if l!=k and abs(int(p[:,k]@p[:,l]))==16]
    assert aliases["prompt*tool_schema"]  # do not pretend interactions are individually estimable.
    return x,aliases

def admit(rows,compatible):
    # Never silently delete invalid rows and continue to claim a regular design.
    bad=[i for i,row in enumerate(rows) if not compatible(row)]
    if bad:
        return {"status":"REDESIGN_REQUIRED","excluded_rows":bad,"planned_runs":0}
    return {"status":"READY","excluded_rows":[],"planned_runs":len(rows)}

def main():
    out=pathlib.Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    x,aliases=plan()
    allowed=admit(x,lambda row:True)
    restricted=admit(x,lambda row:not(row[4]==1 and row[3]==-1))
    assert allowed["status"]=="READY" and restricted["status"]=="REDESIGN_REQUIRED"
    # Known effects on an arbitrary synthetic response, not real goodput.
    beta=np.array([3,11,0,7,0,-2,0,0])
    rng=np.random.default_rng(2701)
    data=[]
    block_estimates=[]
    for block in range(6):
        order=rng.permutation(len(x))
        noise=rng.normal(0,0.25,len(x))
        y=50+4*block+x@beta+5*x[:,0]*x[:,1]+noise
        for ordinal,i in enumerate(order):
            data.append({"block":block,"order":ordinal,"configuration":dict(zip(NAMES,map(int,x[i]))),"response":float(y[i]),"scope":"FRAMEWORK_PROVING_ONLY"})
        block_estimates.append((x.T@y/len(x)).tolist())
    effects=np.mean(block_estimates,axis=0)
    ranking=sorted(zip(NAMES,effects.tolist()),key=lambda p:abs(p[1]),reverse=True)
    assert [k for k,v in ranking[:3]]==["tool_schema","context","prompt"]
    assert np.max(np.abs(effects-beta))<0.2
    # De-alias one selected interaction with an independent 2x2 follow-up,
    # fixing all other factors at baseline. This does not resolve all aliases.
    rows=[]
    for a,b in itertools.product((-1,1),repeat=2):
        v=np.full(8,-1);v[0]=a;v[1]=b
        y=float(50+v@beta+5*a*b)
        rows.append([a,b,y])
    interaction=sum(a*b*y for a,b,y in rows)/4
    assert interaction==5
    # Fail closed for missing observations or duplicate trial identities.
    def valid_block(records):
        return len(records)==16 and {digest(t["configuration"]) for t in records}=={digest(dict(zip(NAMES,map(int,row)))) for row in x}
    first=[t for t in data if t["block"]==0]
    assert valid_block(first) and not valid_block(first[:-1]) and not valid_block(first[:-1]+first[:1])
    receipt={"scope":"FRAMEWORK_PROVING_ONLY","upstream":SOURCE,"generator":GEN,"design_runs":len(x),"full_factorial":256,"main_effect_rank":int(np.linalg.matrix_rank(np.column_stack([np.ones(16),x]))),"aliases":aliases,"blocks":6,"screen_trials":len(data),"main_effect_coefficients":dict(zip(NAMES,effects.tolist())),"known_coefficients":dict(zip(NAMES,beta.tolist())),"ranking":ranking,"interaction_followup":{"factors":["prompt","tool_schema"],"coefficient":interaction,"rows":rows},"compatibility":{"allowed":allowed,"restricted":restricted},"negative_controls":{"missing_block_row":"REJECT","duplicate_configuration":"REJECT"},"plan_digest":digest(x.tolist()),"status":"PASS"}
    for name,payload in [("doe-receipt.json",receipt),("synthetic-observations.json",data)]:
        (out/name).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("ACTOR_DOE="+json.dumps(receipt),flush=True)

if __name__=="__main__": main()
