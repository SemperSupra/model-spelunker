"""Counterbalanced complete finite campaign comparison with clean dependencies."""
import json,pathlib,subprocess,sys,shutil
from overhead_proof import measure
from hydration_proof import PIN
HERE=pathlib.Path(__file__).resolve().parent

def main(out):
    out.mkdir();rows=[]
    for block in range(2):
        for backend in (["exact","optuna"] if block==0 else ["optuna","exact"]):
            d=out/f"{block}-{backend}";d.mkdir()
            env=d/"env";setup={"venv":measure([sys.executable,"-m","venv",str(env)])}
            py=env/"bin/python"
            if backend=="optuna":
                setup["install"]=measure([str(py),"-m","pip","install","--disable-pip-version-check","--no-cache-dir",PIN])
            else:
                # Demonstrate no importable Optuna dependency in the exact arm.
                subprocess.run([str(py),"-c","import importlib.util; assert importlib.util.find_spec('optuna') is None"],check=True)
            with (d/"dependencies.txt").open("w") as f:
                setup["inventory"]=measure([str(py),"-m","pip","freeze"],stdout=f)
            run=measure([str(py),str(HERE/"adaptive_proof.py"),str(d/"campaign"),backend])
            result=json.loads((d/"campaign/summary.json").read_text())
            assert result["screen"]["selector_backend"]==backend
            assert result["screen"]["pareto"]==["cheap"] and result["screen"]["candidate"]=="cheap"
            assert result["accepted"]==12 and result["attempts"]==15
            assert result["confirmation"]["candidate"][0]==result["confirmation"]["baseline"][0]==3
            assert not result["promotion_authorized"]
            total=sum(v["cpu_seconds"] for v in setup.values())+run["cpu_seconds"]
            wall=sum(v["wall_seconds"] for v in setup.values())+run["wall_seconds"]
            rows.append({"block":block,"backend":backend,"setup":setup,"campaign":run,"total_cpu_seconds":total,"total_wall_seconds":wall,"accepted":12,"attempts":15,"trial_cpu_seconds":result["all_attempt_cpu_seconds"],"campaign_nontrial_cpu_seconds":max(0,run["cpu_seconds"]-result["all_attempt_cpu_seconds"])})
            shutil.rmtree(env)
    totals={}
    for arm in ("exact","optuna"):
        v=[r for r in rows if r["backend"]==arm]
        cpu=sum(r["total_cpu_seconds"] for r in v)
        totals[arm]={"accepted":24,"attempts":30,"cpu_seconds":cpu,"wall_seconds":sum(r["total_wall_seconds"] for r in v),"cpu_seconds_per_accepted":cpu/24}
    result={"scope":"FRAMEWORK_PROVING_ONLY","paired_blocks":2,"rows":rows,"totals":totals,"selection_and_confirmation_parity":True,"exact_no_optuna_dependency":True,"promotion_authorized":False,"limitations":"one public runner; same synthetic task; counterbalanced clean environment setup, no pip cache; optimizer for fully evaluated finite observations only; excludes checkout/provisioning/external server CPU"}
    (out/"summary.json").write_text(json.dumps(result,indent=2))
    print("FINITE_CAMPAIGN="+json.dumps(result),flush=True)
if __name__=="__main__":main(pathlib.Path(sys.argv[1]).resolve())
