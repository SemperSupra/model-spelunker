"""One blocked comparison: independent clean environments vs grouped reuse.
No cache publication, no cross-runner claim. Actual identical adaptive workload.
"""
import json,pathlib,random,subprocess,sys,resource,time
from overhead_proof import measure
HERE=pathlib.Path(__file__).resolve().parent
PIN="git+https://github.com/optuna/optuna.git@0abf066c1e5d9d83987986869daa3c2bb23df519"
def main():
    out=pathlib.Path(sys.argv[1]).resolve();out.mkdir()
    order=["separate","grouped"];random.Random(1398).shuffle(order)
    results={};manifests=[]
    for arm in order:
        d=out/arm;d.mkdir();setup=[];campaign=[]
        for i in range(2):
            env=d/("env-"+str(i) if arm=="separate" else "env-0")
            py=env/"bin/python"
            if not env.exists():
                v=measure([sys.executable,"-m","venv",str(env)])
                p=measure([str(py),"-m","pip","install","--disable-pip-version-check","--no-cache-dir",PIN])
                inventory=d/("freeze-"+str(i)+".txt")
                with inventory.open("w") as f:fr=measure([str(py),"-m","pip","freeze"],stdout=f)
                manifests.append(inventory.read_text())
                setup.append({"venv":v,"install":p,"inventory":fr})
            dest=d/("campaign-"+str(i))
            m=measure([str(py),str(HERE/"adaptive_proof.py"),str(dest),"optuna"])
            s=json.loads((dest/"summary.json").read_text())
            assert s["screen"]["candidate"]=="cheap" and s["accepted"]==12 and s["attempts"]==15
            campaign.append({"measurement":m,"accepted":s["accepted"],"attempts":s["attempts"],"trial_cpu_seconds":s["all_attempt_cpu_seconds"]})
        total=sum(x["cpu_seconds"] for s in setup for x in s.values())+sum(c["measurement"]["cpu_seconds"] for c in campaign)
        wall=sum(x["wall_seconds"] for s in setup for x in s.values())+sum(c["measurement"]["wall_seconds"] for c in campaign)
        results[arm]={"setup_count":len(setup),"setup":setup,"campaigns":campaign,"accepted":24,"attempts":30,"total_cpu_seconds":total,"measured_wall_seconds":wall,"cpu_seconds_per_accepted":total/24}
        # Only receipts and dependency inventory go to artifact, never disposable env.
        import shutil
        for env in d.glob("env-*"):shutil.rmtree(env)
    same=len(set(manifests))==1
    summary={"scope":"FRAMEWORK_PROVING_ONLY","order":order,"arms":results,"dependency_inventories_identical":same,"status":"COMPARABLE" if same else "DEPENDENCY_DRIFT","limitations":"one runner/one group per treatment; no generalization; fresh venv and no pip cache, shared reuse in same job only; excludes provisioning/checkout and external network server CPU"}
    (out/"summary.json").write_text(json.dumps(summary,indent=2))
    print("HYDRATION_COMPARISON="+json.dumps(summary),flush=True)
if __name__=="__main__":main()
