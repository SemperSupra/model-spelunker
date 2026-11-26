"""Exact finite Pareto selection for fully observed, bounded two-objective sets.
No inference, admission, scheduling, adaptive sampling, or automatic promotion.
"""
import math

def validated(points):
    if not isinstance(points,dict) or not 1<=len(points)<=1000:
        raise ValueError("expected 1..1000 fully observed candidates")
    out={}
    for key,p in points.items():
        if not isinstance(key,str) or not key or not isinstance(p,(list,tuple)) or len(p)!=2:
            raise ValueError("invalid candidate or objective vector")
        q,c=p
        if type(q) is not int or q<0 or type(c) not in (int,float) or not math.isfinite(c) or c<0:
            raise ValueError("invalid acceptance or cost")
        out[key]=(q,c)
    return out

def exact(points):
    points=validated(points)
    # Sort acceptance descending and cost ascending, then sweep. Equal vectors
    # remain nondominated together; a lower-acceptance equal-cost vector is dominated.
    best_cost=math.inf;last_kept=None;front=[]
    for key,(q,c) in sorted(points.items(),key=lambda kv:(-kv[1][0],kv[1][1],kv[0])):
        if c<best_cost or last_kept==(q,c):
            front.append(key);best_cost=c;last_kept=(q,c)
    return sorted(front)

def native(points):
    points=validated(points)
    import optuna
    optuna.logging.set_verbosity(optuna.logging.ERROR)
    study=optuna.create_study(directions=["maximize","minimize"],sampler=optuna.samplers.GridSampler({"arm":sorted(points)},seed=19))
    study.optimize(lambda t:points[t.suggest_categorical("arm",sorted(points))],n_trials=len(points))
    return sorted(t.params["arm"] for t in study.best_trials)

def selftest():
    assert exact({"a":[3,1],"b":[3,1],"c":[0,1],"d":[2,0]})==["a","b","d"]
    assert exact({"a":[0,0],"b":[0,1]})==["a"]
    for points in ({},{"a":[1,None]},{"a":[True,1]},{"a":[1,float("nan")]},{"a":[1,-1]},{"a":[1,2,3]}):
        try:exact(points)
        except ValueError:pass
        else:raise AssertionError("invalid points accepted")
    # Independent quadratic oracle, including duplicates and ties.
    import random
    rng=random.Random(1400)
    for n in range(1,65):
        points={str(i):(rng.randrange(5),rng.randrange(10)) for i in range(n)}
        want=sorted(k for k,p in points.items() if not any(q[0]>=p[0] and q[1]<=p[1] and q!=p for q in points.values()))
        assert exact(points)==want
    print("FINITE_SELECTOR_SELFTEST=PASS")

if __name__=="__main__":selftest()
