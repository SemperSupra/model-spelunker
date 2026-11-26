"""Paired block analysis for bounded methodology experiments.
Exact sign-flip reference distribution requires exchangeability under the null.
No statistical significance or operational qualification from two blocks.
"""
import itertools,json,math,pathlib,sys,statistics
from collections import defaultdict

def paired(rows,arms,expected_blocks):
    if len(arms)!=2 or len(set(arms))!=2 or not 1<=len(expected_blocks)<=16:
        raise ValueError("invalid paired design")
    cells={};runs=set()
    for r in rows:
        block=r["block"];arm=r["arm"];key=(block,arm)
        if block not in expected_blocks or arm not in arms or key in cells or r["run_id"] in runs:
            raise ValueError("unexpected cell or duplicate identity")
        if r["status"]!="OBSERVED" or type(r["accepted"]) is not bool:
            raise ValueError("incomplete or censored block; preserve it separately")
        v=r["value"]
        if type(v) not in (int,float) or not math.isfinite(v) or v<0:raise ValueError("invalid measurement")
        cells[key]=r;runs.add(r["run_id"])
    if set(cells)!={(b,a) for b in expected_blocks for a in arms}:raise ValueError("incomplete block")
    differences=[]
    for b in sorted(expected_blocks):
        a,c=(cells[b,arm] for arm in arms)
        if a["task_id"]!=c["task_id"] or a["accepted"]!=c["accepted"] or not a["accepted"]:
            raise ValueError("task or outcome parity not established")
        differences.append(c["value"]-a["value"])
    observed=abs(sum(differences));count=0
    for signs in itertools.product((-1,1),repeat=len(differences)):
        count+=abs(sum(x*s for x,s in zip(differences,signs)))>=observed-1e-12
    return {"blocks":len(differences),"paired_differences":differences,"mean_difference":statistics.mean(differences),"exact_two_sided_sign_flip_p":count/(2**len(differences)),"minimum_possible_two_sided_p":2/(2**len(differences)) if len(differences)>1 else 1,"disposition":"DESCRIPTIVE_ONLY" if len(differences)<6 else "REFERENCE_DISTRIBUTION_ONLY","assumptions":"exchangeable paired differences under null; no multiplicity adjustment; not an operational acceptance rule"}

def controls():
    rows=[{"block":b,"arm":a,"run_id":f"{b}-{a}","task_id":f"t{b}","accepted":True,"status":"OBSERVED","value":10 if a=="base" else 12} for b in range(8) for a in ("base","new")]
    assert paired(rows,("base","new"),set(range(8)))["exact_two_sided_sign_flip_p"]==2/256
    zeros=[{**r,"value":10} for r in rows];assert paired(zeros,("base","new"),set(range(8)))["exact_two_sided_sign_flip_p"]==1
    badcases=[rows[:-1],rows+[rows[0]], [{**r,"run_id":"same"} for r in rows],[{**r,"status":"CENSORED"} if i==0 else r for i,r in enumerate(rows)],[{**r,"task_id":"other"} if i==0 else r for i,r in enumerate(rows)],[{**r,"accepted":False} if i==0 else r for i,r in enumerate(rows)],[{**r,"value":float("nan")} if i==0 else r for i,r in enumerate(rows)]]
    for bad in badcases:
        try:paired(bad,("base","new"),set(range(8)))
        except ValueError:pass
        else:raise AssertionError("invalid paired evidence accepted")
    return len(badcases)

def main(src,out):
    out.mkdir();data=json.loads(src.read_text());rows=data["rows"];results={}
    assert data["scope"]=="FRAMEWORK_PROVING_ONLY"
    for family in ("repair","lookup"):
        for stage in ("screen","confirm"):
            selected=[{"block":r["block"],"arm":r["arm"],"run_id":r["run_id"],"task_id":r["task_id"],"accepted":r["accepted"],"status":"OBSERVED","value":r["cpu_seconds"]} for r in rows if r["family"]==family and r["stage"]==stage and r["arm"] in (family,"composite")]
            result=paired(selected,(family,"composite"),{0,1});assert result["disposition"]=="DESCRIPTIVE_ONLY"
            results[f"{family}-{stage}"]=result
    summary={"scope":"FRAMEWORK_PROVING_ONLY","actual_paired_analyses":4,"synthetic_positive_controls":2,"negative_controls":controls(),"results":results,"promotion_authorized":False,"limitations":"two paired blocks per actual contrast; minimum possible two-sided p=.5; no statistical confidence claim, no pooling across task families or screening/confirmation, resource variability retained"}
    (out/"summary.json").write_text(json.dumps(summary,indent=2));print("PAIRED_STATS="+json.dumps(summary),flush=True)
if __name__=="__main__":main(pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]))
