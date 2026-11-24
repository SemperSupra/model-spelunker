"""Prove upstream pruning and Pareto reduction on a synthetic finite surface.
No model calls or operational qualification. Fixed policy gate is not a knob.
"""
import json, pathlib, sys, random
import optuna
from optuna.trial import TrialState

NAMES=["baseline","fast","balanced","quality","dominated","unstable","ineligible"]
# Quality/latency are arbitrary fixture units, not inferred real actor measurements.
POINTS={"baseline":(70,10),"fast":(72,5),"balanced":(90,8),"quality":(97,15),"dominated":(65,12),"unstable":(45,11),"ineligible":(100,1)}
ELIGIBLE=[n for n in NAMES if n!="ineligible"]
def permitted(name): return name in ELIGIBLE
def dominates(a,b): return a[0]>=b[0] and a[1]<=b[1] and a!=b
def oracle_front(points):
    return {n for n,p in points.items() if not any(dominates(q,p) for m,q in points.items() if m!=n)}
def main():
    out=pathlib.Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    # Complete finite Pareto reference via actual Optuna GridSampler.
    assert not permitted("ineligible")
    multi=optuna.create_study(directions=["maximize","minimize"],sampler=optuna.samplers.GridSampler({"candidate":ELIGIBLE},seed=19))
    multi_rows=[]
    def objectives(trial):
        n=trial.suggest_categorical("candidate",ELIGIBLE)
        assert permitted(n)
        q,t=POINTS[n]
        multi_rows.append({"candidate":n,"quality":q,"latency":t})
        return q,t
    multi.optimize(objectives,n_trials=len(ELIGIBLE))
    want=oracle_front({n:POINTS[n] for n in ELIGIBLE})
    got={t.params["candidate"] for t in multi.best_trials}
    assert want==got=={"fast","balanced","quality"}
    # A separate single-objective bounded screen with identical task block order.
    # Quality only here; never substitute this result for the Pareto front.
    race=optuna.create_study(direction="maximize",sampler=optuna.samplers.RandomSampler(seed=31),pruner=optuna.pruners.SuccessiveHalvingPruner(min_resource=2,reduction_factor=2,min_early_stopping_rate=0))
    order=["quality","balanced","fast","baseline","dominated","unstable"]
    for n in order: race.enqueue_trial({"candidate":n})
    offsets=[-2,1,0,2,-1,0,1,-1]
    race_rows=[]
    def objective(trial):
        n=trial.suggest_categorical("candidate",ELIGIBLE)
        assert permitted(n)
        q,_=POINTS[n]
        observed=[]
        for step,d in enumerate(offsets,1):
            observed.append(q+d)
            mean=sum(observed)/len(observed)
            trial.report(mean,step)
            if trial.should_prune():
                race_rows.append({"candidate":n,"observations":len(observed),"outcome":"PRUNED","mean_observed":mean})
                raise optuna.TrialPruned()
        race_rows.append({"candidate":n,"observations":len(observed),"outcome":"COMPLETE","mean_observed":mean})
        return mean
    race.optimize(objective,n_trials=len(order))
    used=sum(x["observations"] for x in race_rows)
    assert len(race_rows)==len(order) and used<len(order)*len(offsets)
    assert race.best_trial.params["candidate"]=="quality"
    assert any(t.state==TrialState.PRUNED for t in race.trials)
    # All pruned observations remain censored; independent sealed holdout.
    heldout=[-1,2,-2,1]
    confirmed={n:sum(POINTS[n][0]+d for d in heldout)/len(heldout) for n in sorted(want|{"baseline"})}
    assert max(confirmed,key=confirmed.get)=="quality"
    receipt={"scope":"FRAMEWORK_PROVING_ONLY","upstream":"0abf066c1e5d9d83987986869daa3c2bb23df519","pareto_front":sorted(got),"independent_front":sorted(want),"ineligible_rejected":True,"racing_order":order,"racing":race_rows,"observations_used":used,"exhaustive_racing_observations":len(order)*len(offsets),"holdout":confirmed,"limitations":"fixed synthetic order; not order-robustness or optimization efficacy proof; pruned trials not full outcomes","status":"PASS"}
    for name,payload in [("receipt.json",receipt),("pareto-observations.json",multi_rows)]:
        (out/name).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("RACING_PARETO="+json.dumps(receipt),flush=True)
if __name__=="__main__": main()
