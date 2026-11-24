"""R4: bounded screen -> select -> held-out confirmation using existing task/resource runner.
Synthetic controls only; no authority, no deployment, no new runner or scheduler.
"""
import json,random,hashlib,pathlib,subprocess,sys,shutil,time
import optuna
ROOT=pathlib.Path(__file__).resolve().parents[2]
HERE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"qualification/resource_join_r0"))
from prove import validate
sys.path.insert(0,str(HERE))
from workbench import load
from resource_view import attach
ARMS=["cheap","expensive","rejected"]
BUDGET=15
def main(out):
    out.mkdir();rows=[];rng=random.Random(1394)
    receipts=out/"receipts";resources=out/"resources";receipts.mkdir();resources.mkdir()
    start=time.monotonic()
    def trial(stage,block,arm):
        if len(rows)>=BUDGET:raise ValueError("trial budget exhausted")
        name=f"{stage}-{block}-{arm}";d=out/name
        subprocess.run([sys.executable,str(ROOT/"qualification/resource_join_r0/prove.py"),"trial",str(d),arm,str(block)],check=True,timeout=75)
        raw=(d/"receipt.json").read_bytes();side=validate(json.loads((d/"resource.json").read_bytes()),raw)
        assert side["treatment"]==arm and side["block"]==block
        shutil.copyfile(d/"receipt.json",receipts/(name+".json"));shutil.copyfile(d/"resource.json",resources/(name+".json"))
        rows.append({"stage":stage,"block":block,"arm":arm,"run_id":side["run_id"],"accepted":side["accepted"],"cpu_seconds":side["metrics"]["cpu_seconds"]["value"],"receipt_sha256":side["receipt_sha256"]})
    def block(stage,i,arms):
        order=list(arms);rng.shuffle(order)
        for arm in order:trial(stage,i,arm)
    for i in range(3):block("screen",i,ARMS)
    def score(arm,stage):
        a=[x for x in rows if x["arm"]==arm and x["stage"]==stage]
        return sum(x["accepted"] for x in a),sum(x["cpu_seconds"] for x in a)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study=optuna.create_study(directions=["maximize","minimize"],sampler=optuna.samplers.GridSampler({"arm":ARMS},seed=19))
    study.optimize(lambda t:score(t.suggest_categorical("arm",ARMS),"screen"),n_trials=3)
    scores={a:score(a,"screen") for a in ARMS}
    def dominates(a,b):return a[0]>=b[0] and a[1]<=b[1] and a!=b
    oracle={a for a in ARMS if not any(dominates(scores[b],scores[a]) for b in ARMS if a!=b)}
    assert oracle=={t.params["arm"] for t in study.best_trials}
    # Acceptance is a hard condition for this fixed synthetic task.
    eligible=[a for a in oracle if scores[a][0]==3]
    assert eligible
    winner=min(eligible,key=lambda a:scores[a][1])
    # Holdout observations are not available during screen selection.
    baseline="expensive";assert winner=="cheap"
    selection={"screen_scores":scores,"pareto":sorted(oracle),"candidate":winner,"baseline":baseline,"scope":"FRAMEWORK_PROVING_ONLY","promotion_authorized":False}
    (out/"selection-before-confirmation.json").write_text(json.dumps(selection,indent=2))
    for i in range(3,6):block("confirm",i,[winner,baseline])
    confirmed=score(winner,"confirm");reference=score(baseline,"confirm")
    assert confirmed[0]==reference[0]==3 and confirmed[1]<reference[1]
    assert len(rows)==BUDGET and len({x["run_id"] for x in rows})==BUDGET
    view=load(receipts);attach(view,resources)
    assert view["summary"]=={"total":15,"accepted":12,"not_accepted":3}
    cpu=sum(x["cpu_seconds"] for x in rows);assert abs(cpu-view["resources"]["cpu_seconds"])<1e-9
    # Actual shared CLI/HTML renderer; no duplicate dashboard.
    subprocess.run([sys.executable,str(HERE/"workbench.py"),"render","--receipts",str(receipts),"--resources",str(resources),"--output",str(out/"campaign.html")],check=True,timeout=30)
    summary={"scope":"FRAMEWORK_PROVING_ONLY","screen":selection,"confirmation":{"candidate":confirmed,"baseline":reference,"paired_blocks":3},"attempts":len(rows),"accepted":12,"all_attempt_cpu_seconds":cpu,"all_attempt_cpu_seconds_per_accepted":cpu/12,"elapsed_seconds":time.monotonic()-start,"rows":rows,"promotion_authorized":False,"limitations":"fixed synthetic arms, three held-out repetition blocks of same task, no cross-task generalization; observed runner/child CPU excludes provisioning, Optuna overhead and remote resources; no real actor optimization"}
    (out/"summary.json").write_text(json.dumps(summary,indent=2));print("ADAPTIVE_LOOP="+json.dumps(summary),flush=True)
if __name__=="__main__":main(pathlib.Path(sys.argv[1]).resolve())
