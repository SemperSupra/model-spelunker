"""Finite decision-cost comparison on actual screen evidence and synthetic edge cases.
Optuna remains a candidate for larger/adaptive searches; no production selection.
"""
import argparse,json,pathlib,random,subprocess,sys,time,resource,math
HERE=pathlib.Path(__file__).resolve().parent
def exact(points):
    # Equal points both nondominated; maximize accepted, minimize measured cost.
    return sorted(k for k,p in points.items() if not any(q[0]>=p[0] and q[1]<=p[1] and q!=p for q in points.values()))
def native(points):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.ERROR)
    study=optuna.create_study(directions=["maximize","minimize"],sampler=optuna.samplers.GridSampler({"arm":sorted(points)},seed=19))
    study.optimize(lambda t:points[t.suggest_categorical("arm",sorted(points))],n_trials=len(points))
    return sorted(t.params["arm"] for t in study.best_trials)
def worker(mode,inp,out):
    start=time.monotonic()
    cases=json.loads(inp.read_text())
    fn=exact if mode=="exact" else native
    fronts=[fn(case["points"]) for case in cases]
    out.write_text(json.dumps({"fronts":fronts,"inner_wall_seconds":time.monotonic()-start}))
def main(src,out):
    out.mkdir()
    actual=json.loads(src.read_text())["screen"]["screen_scores"]
    cases=[{"id":"actual-screen","points":actual},{"id":"tie","points":{"a":[3,1],"b":[3,1],"c":[0,2]}},{"id":"tradeoff","points":{"a":[3,2],"b":[2,1],"c":[1,3]}},{"id":"zero-success","points":{"a":[0,1],"b":[0,2]}}]
    rng=random.Random(1399)
    for size in (4,8,16,32):
        for rep in range(4):
            cases.append({"id":f"synthetic-{size}-{rep}","points":{f"a{i}":[rng.randrange(4),rng.randrange(1,51)/10] for i in range(size)}})
    inp=out/"cases.json";inp.write_text(json.dumps(cases))
    results=[]
    for block in range(4):
        for mode in (["exact","optuna"] if block%2==0 else ["optuna","exact"]):
            dst=out/f"{block}-{mode}.json"
            before=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.monotonic()
            subprocess.run([sys.executable,__file__,"worker",mode,str(inp),str(dst)],check=True,timeout=60)
            elapsed=time.monotonic()-start;after=resource.getrusage(resource.RUSAGE_CHILDREN)
            data=json.loads(dst.read_text())
            results.append({"block":block,"mode":mode,"cpu_seconds":after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,"wall_seconds":elapsed,"fronts":data["fronts"]})
    expected=[exact(c["points"]) for c in cases]
    # independently specified edge-case answers; actual fixture selection from prior experiment.
    assert expected[:4]==[["cheap"],["a","b"],["a","b"],["a"]]
    assert all(r["fronts"]==expected for r in results)
    totals={m:{"cpu_seconds":sum(r["cpu_seconds"] for r in results if r["mode"]==m),"wall_seconds":sum(r["wall_seconds"] for r in results if r["mode"]==m)} for m in ("exact","optuna")}
    result={"scope":"FRAMEWORK_PROVING_ONLY","cases":len(cases),"paired_blocks":4,"matching_fronts":len(cases)*4,"totals":totals,"results":results,"limitations":"fully evaluated finite observations only, no adaptive sampling or racing; includes fresh process/import overhead, excludes dependency setup (measured separately); reference implementation reused from adaptive proof dominance oracle"}
    (out/"summary.json").write_text(json.dumps(result,indent=2));print("FINITE_SELECTOR="+json.dumps({k:v for k,v in result.items() if k!="results"}),flush=True)
if __name__=="__main__":
    if sys.argv[1]=="worker":worker(sys.argv[2],pathlib.Path(sys.argv[3]),pathlib.Path(sys.argv[4]))
    else:main(pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]))
