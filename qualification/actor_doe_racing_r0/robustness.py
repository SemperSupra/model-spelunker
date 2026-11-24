"""Red/blue racing controls: vary order and deliberately late-improving response.
Synthetic known outcomes; no evidence about actual models.
"""
import json,pathlib,random,sys,statistics
import optuna
from optuna.trial import TrialState
NAMES=["steady","late","weak","medium"]
BASE={"steady":[84]*8,"late":[40,42,45,48,99,99,99,99],"weak":[30]*8,"medium":[67]*8}
# The declared decision endpoint weights difficult later blocks; no data leakage to early policy.
def score(values):return sum(values[-4:])/4
def run(seed):
    rng=random.Random(seed)
    shared=[rng.randint(-2,2) for _ in range(8)]
    data={k:[v+d for v,d in zip(BASE[k],shared)] for k in NAMES}
    truth=max(NAMES,key=lambda k:score(data[k]))
    assert truth=="late"
    order=NAMES[:];rng.shuffle(order)
    s=optuna.create_study(direction="maximize",pruner=optuna.pruners.SuccessiveHalvingPruner(min_resource=2,reduction_factor=2))
    for k in order:s.enqueue_trial({"arm":k})
    used=0;rows=[]
    def objective(t):
        nonlocal used
        k=t.suggest_categorical("arm",NAMES)
        for j,v in enumerate(data[k],1):
            used+=1
            t.report(v,j)
            if t.should_prune():rows.append({"arm":k,"observations":j,"state":"PRUNED"});raise optuna.TrialPruned()
        rows.append({"arm":k,"observations":8,"state":"COMPLETE"})
        return score(data[k])
    s.optimize(objective,n_trials=len(NAMES))
    chosen=s.best_trial.params["arm"]
    # Conservative paired-stage policy: no culling before all candidates see
    # the first late/difficult block; only remove a candidate if its best possible
    # endpoint (bounded by preregistered fixture range) cannot beat an incumbent.
    observations={k:[] for k in NAMES};live=set(NAMES);censored=[]
    for j in range(8):
        for k in sorted(live):observations[k].append(data[k][j])
        if j>=4:
            intervals={}
            for k in live:
                observed=observations[k][4:];missing=4-len(observed)
                intervals[k]=((sum(observed)+missing*0)/4,(sum(observed)+missing*102)/4)
            best_lower=max(lo for lo,hi in intervals.values())
            for k,(lo,hi) in intervals.items():
                if hi<best_lower:live.remove(k);censored.append(k)
    assert live
    selected=max(live,key=lambda k:score(observations[k]))
    return {"seed":seed,"order":order,"truth":truth,"native_selection":chosen,"native_observations":used,"native_rows":rows,"guarded_selection":selected,"guarded_observations":sum(map(len,observations.values())),"guarded_censored":censored,"exhaustive_observations":32}
def main():
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    rows=[run(seed) for seed in range(24)]
    assert all(r["guarded_selection"]==r["truth"] for r in rows)
    assert any(r["native_selection"]!=r["truth"] for r in rows)
    summary={"scope":"FRAMEWORK_PROVING_ONLY","repetitions":len(rows),"native_correct":sum(r["native_selection"]==r["truth"] for r in rows),"guarded_correct":sum(r["guarded_selection"]==r["truth"] for r in rows),"native_observations":sum(r["native_observations"] for r in rows),"guarded_observations":sum(r["guarded_observations"] for r in rows),"exhaustive_observations":sum(r["exhaustive_observations"] for r in rows),"rows":rows,"limitations":"constructed late-benefit bounded fixture; conservative rule uses known score bounds, not general-purpose racing or proof against unknown real response surfaces"}
    out=pathlib.Path(sys.argv[1]);out.mkdir();(out/"robustness.json").write_text(json.dumps(summary,indent=2))
    print("RACING_ROBUSTNESS="+json.dumps({k:v for k,v in summary.items() if k!="rows"}),flush=True)
if __name__=="__main__":main()
