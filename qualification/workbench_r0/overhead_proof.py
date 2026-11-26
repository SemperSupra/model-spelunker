"""Measure setup and the complete adaptive child campaign, without double-counting trial CPU."""
import json,math,pathlib,resource,subprocess,sys,time
HERE=pathlib.Path(__file__).resolve().parent
def measure(command,**kwargs):
    before=resource.getrusage(resource.RUSAGE_CHILDREN)
    start=time.monotonic()
    subprocess.run(command,check=True,**kwargs)
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"cpu_seconds":after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,"wall_seconds":time.monotonic()-start}
def main():
    out=pathlib.Path(sys.argv[1]).resolve()
    setup=measure([sys.executable,"-m","pip","install","git+https://github.com/optuna/optuna.git@0abf066c1e5d9d83987986869daa3c2bb23df519"])
    with open("adaptive-dependencies.txt","w") as f:
        freeze=measure([sys.executable,"-m","pip","freeze"],stdout=f)
    campaign=measure([sys.executable,str(HERE/"adaptive_proof.py"),str(out),"optuna"])
    data=json.loads((out/"summary.json").read_text())
    trial_cpu=data["all_attempt_cpu_seconds"]
    remainder=campaign["cpu_seconds"]-trial_cpu
    assert remainder>=-0.001,"trial accounting exceeds enclosing process-tree CPU"
    result={"scope":"FRAMEWORK_PROVING_ONLY","setup_pip":setup,"freeze":freeze,"campaign":campaign,"trial_child_cpu_seconds":trial_cpu,"nontrial_campaign_cpu_seconds":max(0,remainder),"total_setup_campaign_cpu_seconds":setup["cpu_seconds"]+freeze["cpu_seconds"]+campaign["cpu_seconds"],"accepted":data["accepted"],"attempts":data["attempts"],"coverage":"waited descendants of install/freeze and campaign; excludes host provisioning, checkout, browser setup, external services, outer wrapper and network server CPU"}
    result["total_cpu_seconds_per_accepted"]=result["total_setup_campaign_cpu_seconds"]/data["accepted"] if data["accepted"] else None
    (out/"overhead.json").write_text(json.dumps(result,indent=2))
    print("EXPERIMENT_OVERHEAD="+json.dumps(result),flush=True)
if __name__=="__main__":main()
