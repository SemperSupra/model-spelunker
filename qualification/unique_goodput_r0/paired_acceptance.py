"""Paired binary acceptance accounting: fixed intent families, incomplete evidence.
Complement to the paired resource-cost analysis (#372): do not condition success
analysis on both arms succeeding. Scripted controls, not an actor ranking.
"""
import hashlib
import json
import pathlib
import random
import subprocess
import sys
from fractions import Fraction

ROOT=pathlib.Path(__file__).resolve().parents[2]
# Unequal counts by family, deliberately produce opposite pooled/family conclusions.
# Values are authored controls for an oracle, not measurements or estimated effects.
PLAN={
    "f1":{"v1":(False,True)},
    "f2":{"v1":(False,True)},
    "f3":{f"v{i}":(True,False) for i in range(1,5)},
    "f4":{"v1":(True,True),"v2":(False,False)},
}
ARMS=("base","new")

def write(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def sha(b):return "sha256:"+hashlib.sha256(b).hexdigest()
def check(ok,msg):
    if not ok:raise ValueError(msg)

def reduce(rows):
    planned={(f,v,a) for f,variants in PLAN.items() for v in variants for a in ARMS}
    cells={};runs=set()
    for r in rows:
        k=(r["family"],r["variant"],r["arm"])
        check(k in planned and k not in cells,"unknown or duplicate cell")
        check(type(r["accepted"]) is bool,"not a witnessed binary outcome")
        check(isinstance(r["run_id"],str) and r["run_id"] and r["run_id"] not in runs,"duplicate/missing run identity")
        check(r["task_id"]=="paired-"+k[0]+"-"+k[1]+"-v0","wrong task family or variant")
        runs.add(r["run_id"]);cells[k]=int(r["accepted"])
    family=[];plo=Fraction(0);phi=Fraction(0);complete=0;total=0
    for f,variants in PLAN.items():
        lo=Fraction(0);hi=Fraction(0);n=0
        for v in variants:
            base=cells.get((f,v,"base"));new=cells.get((f,v,"new"))
            lower=Fraction((new if new is not None else 0)-(base if base is not None else 1))
            upper=Fraction((new if new is not None else 1)-(base if base is not None else 0))
            lo+=lower;hi+=upper;plo+=lower;phi+=upper;total+=1
            if base is not None and new is not None:n+=1;complete+=1
        family.append({"family":f,"variants":len(variants),"complete_pairs":n,
                       "lower":lo/len(variants),"upper":hi/len(variants)})
    a=sum((x["lower"] for x in family),Fraction(0))/len(family)
    b=sum((x["upper"] for x in family),Fraction(0))/len(family)
    def pair(l,h):return {"lower":float(l),"upper":float(h),"point":float(l) if l==h else None}
    return {"families":len(family),"planned_pairs":total,"complete_pairs":complete,
            "planned_cells":len(planned),"observed_cells":len(cells),"missing_evidence_cells":len(planned)-len(cells),
            "equal_family_weight_delta":pair(a,b),"equal_variant_weight_delta":pair(plo/total,phi/total),
            "family_details":[{"family":x["family"],"variants":x["variants"],"complete_pairs":x["complete_pairs"],**pair(x["lower"],x["upper"])} for x in family],
            "inference":"DESCRIPTIVE_ONLY","promotion_authorized":False,
            "limitations":"Fixed authored task families; variants clustered. Bounds cover missing binary outcome assignments, not sampling uncertainty or confidence intervals. No exchangeability, population generalization or automatic selection assumed."}

def package(out,f,v):
    task=out/"packages"/f/v;(task/"fixture").mkdir(parents=True)
    expected=(f+":"+v+"\n").encode()
    (task/"fixture/intent.txt").write_bytes(expected)
    (task/"verify.py").write_text(
        "import pathlib,sys\np=pathlib.Path(sys.argv[1]); expected="+repr(expected)+"\n"
        "ok={x.name for x in p.iterdir()}=={'intent.txt','result.txt'} and all(x.is_file() and not x.is_symlink() for x in p.iterdir()) and (p/'intent.txt').read_bytes()==expected and (p/'result.txt').read_bytes()==expected\n"
        "raise SystemExit(0 if ok else 1)\n",encoding="utf-8")
    write(task/"task.json",{"schema_version":1,"id":"paired-"+f+"-"+v+"-v0","task_class":"framework.paired-acceptance",
          "instruction":"Copy the exact content of intent.txt into result.txt without changing intent.txt.",
          "fixture":"fixture","verifier":"verify.py","limits":{"wall_seconds":10},
          "success":{"kind":"deterministic-final-state"},"allowed_write_paths":["result.txt"],"projected_tools":["read_file","write_file"]})
    return task

def main(out):
    out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    rng=random.Random(20261126);blocks=[(f,v) for f in PLAN for v in PLAN[f]];rng.shuffle(blocks)
    jobs=[]
    for i,(f,v) in enumerate(blocks):
        task=package(out,f,v)
        for arm in (ARMS if i%2==0 else tuple(reversed(ARMS))):
            jobs.append((f,v,arm,task))
    rows=[]
    for index,(f,v,arm,task) in enumerate(jobs):
        d=out/"trials"/str(index);d.mkdir(parents=True)
        expected=PLAN[f][v][ARMS.index(arm)]
        meta=d/"candidate.json";exp=d/"experiment.json";receipt=d/"receipt.json"
        task_id="paired-"+f+"-"+v+"-v0"
        write(meta,{"harness":{"name":"scripted-paired-binary"},"model":{"id":"none"},"toolset":["read_file","write_file"],"arm":arm})
        write(exp,{"schema_version":2,"id":"paired-acceptance-controls-r0","task":{"id":task_id},"claim_type":"framework-proving",
                   "experimental_role":"control","design_block":f+"/"+v,"primary_responses":["acceptance"]})
        code="from pathlib import Path;Path('result.txt').write_bytes("+("Path('intent.txt').read_bytes()" if expected else "b'WRONG'")+")"
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,
             "--substrate-profile-id","framework-"+sys.platform,"--substrate-profile-commit",commit,
             "--experiment",str(exp),str(task),str(meta),str(receipt),"--",sys.executable,"-c",code]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
        check(receipt.is_file(),"missing receipt")
        raw=receipt.read_bytes();r=json.loads(raw);obs=r["observation"]
        check(r["task"]["id"]==task_id and r["task"]["source_commit"]==commit and r["experiment"]["claim_type"]=="framework-proving","identity")
        check(type(obs["success"]) is bool and obs["success"] is expected and p.returncode==(0 if expected else 1),"unexpected outcome")
        rows.append({"family":f,"variant":v,"arm":arm,"task_id":task_id,"run_id":r["run_id"],"accepted":obs["success"],"receipt_sha256":sha(raw)})
    summary=reduce(rows)
    check(summary["equal_family_weight_delta"]["point"]==0.25,"family weighting control failed")
    check(summary["equal_variant_weight_delta"]["point"]==-0.25,"variant weighting control failed")
    # Missing one observed gain from f1 (new succeeds, base fails): no silent
    # deletion or imputed failure; bound the planned denominator.
    partial=reduce([r for r in rows if (r["family"],r["variant"],r["arm"])!=("f1","v1","new")])
    check(partial["missing_evidence_cells"]==1 and partial["complete_pairs"]==7 and
          partial["equal_family_weight_delta"]=={"lower":0.0,"upper":0.25,"point":None},"missing evidence bound")
    negatives=[rows+[rows[0]],
               [{**r,"family":"unknown"} if i==0 else r for i,r in enumerate(rows)],
               [{**r,"accepted":None} if i==0 else r for i,r in enumerate(rows)],
               [{**r,"run_id":"duplicate"} for r in rows],
               [{**r,"task_id":"wrong"} if i==0 else r for i,r in enumerate(rows)]]
    for bad in negatives:
        try:reduce(bad)
        except ValueError:continue
        raise RuntimeError("invalid paired evidence accepted")
    result={"scope":"FRAMEWORK_PROVING_ONLY","source_commit":commit,"actual_receipts":len(rows),
            "complete":summary,"missing_evidence_control":partial,"negative_controls_rejected":len(negatives),
            "rows":rows,"promotion_authorized":False}
    write(out/"summary.json",result);print("PAIRED_ACCEPTANCE="+json.dumps(result),flush=True)
if __name__=="__main__":main(pathlib.Path(sys.argv[1]).resolve())
