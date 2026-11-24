"""Exercise actual canonical runner plus human and machine projections."""
import copy,hashlib,json,os,pathlib,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[2]
HERE=pathlib.Path(__file__).resolve().parent
OUT=pathlib.Path(sys.argv[1]).resolve();OUT.mkdir(parents=True,exist_ok=True)
RECEIPTS=OUT/"receipts";RECEIPTS.mkdir()
def run(args):
    return subprocess.run([sys.executable,*map(str,args)],cwd=ROOT,capture_output=True,text=True,timeout=60)
def cli(*args):
    p=subprocess.run([sys.executable,str(HERE/"workbench.py"),*map(str,args)],cwd=OUT,capture_output=True,text=True,timeout=60)
    assert p.returncode==0,p.stderr
    return json.loads(p.stdout)
metadata=OUT/"candidate.json";metadata.write_text(json.dumps({"harness":{"name":"synthetic-control"},"model":{"id":"none"},"toolset":["write_file"]}))
commit=os.environ.get("GITHUB_SHA") or subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
task=ROOT/"qualification/tasks/text-repair-v0"
exp=OUT/"experiment.json";exp.write_text(json.dumps({"schema_version":2,"id":"workbench-r0","task":{"id":"text-repair-v0"},"claim_type":"framework-proving","experimental_role":"control","primary_responses":["acceptance"]}))
for i in range(6):
    good=i%2==0
    path=RECEIPTS/(str(i)+".json")
    value="READY" if good else "WRONG"
    p=run([ROOT/"qualification/run_task.py","--task-commit",commit,"--substrate-profile-id","framework-"+sys.platform,"--substrate-profile-commit",commit,"--experiment",exp,task,metadata,path,"--",sys.executable,"-c",f"from pathlib import Path; Path('value.txt').write_bytes({(value+chr(10)).encode()!r})"])
    assert path.exists(),p.stderr
    assert json.loads(path.read_text())["observation"]["success"] is good
t=time.perf_counter()
discovery=cli("discover");assert discovery["scope"]=="FRAMEWORK_PROVING_ONLY"
status=cli("status","--receipts",RECEIPTS);assert status["summary"]=={"total":6,"accepted":3,"not_accepted":3}
for row in status["runs"]:
    assert cli("evidence","--receipts",RECEIPTS,"--run-id",row["run_id"])==row
    assert row["promotion"]=="NOT_AUTHORIZED"
assert run([HERE/"workbench.py","evidence","--receipts",RECEIPTS,"--run-id","absent"]).returncode==2
target=OUT/"workbench.html";cli("render","--receipts",RECEIPTS,"--output",target)
assert run([HERE/"workbench.py","render","--receipts",RECEIPTS,"--output",target]).returncode==2
summary={"scope":"FRAMEWORK_PROVING_ONLY","platform":sys.platform,"actual_canonical_receipts":6,"positive":3,"negative":3,"cli_evidence_parity":6,"unknown_run_rejected":True,"overwrite_rejected":True,"cli_journey_s":time.perf_counter()-t}
# R1: adversarial input is not operational evidence; exercise exact same CLI.
badroot=OUT/"negative-inputs";badroot.mkdir()
original=json.loads((RECEIPTS/"0.json").read_text())
def negative(name,mutate):
    folder=badroot/name;folder.mkdir()
    r=copy.deepcopy(original);mutate(r)
    (folder/"receipt.json").write_text(json.dumps(r))
    p=run([HERE/"workbench.py","status","--receipts",folder])
    assert p.returncode==2,(name,p.stdout,p.stderr)
    assert json.loads(p.stderr)["error"]=="INVALID_INPUT"
for name,mutation in [
    ("wrong-purpose",lambda r:r["experiment"].update(claim_type="operational-observation")),
    ("legacy",lambda r:r.update(schema_version=1)),
    ("no-experiment",lambda r:r.pop("experiment")),
    ("unknown-termination",lambda r:r["observation"].update(termination_class="unknown")),
    ("contradiction",lambda r:r["observation"].update(success=False)),
    ("negative-time",lambda r:r["observation"].update(wall_seconds=-1)),
    ("nonfinite-time",lambda r:r["observation"].update(wall_seconds=float("nan"))),
    ("wrong-acceptance-type",lambda r:r["observation"].update(success="true")),
]:
    negative(name,mutation)
folder=badroot/"divergent-duplicate";folder.mkdir()
(folder/"first.json").write_text(json.dumps(original))
changed=copy.deepcopy(original);changed["observation"]["wall_seconds"]+=1
(folder/"second.json").write_text(json.dumps(changed))
assert run([HERE/"workbench.py","status","--receipts",folder]).returncode==2
empty=OUT/"empty";empty.mkdir()
assert cli("status","--receipts",empty)["summary"]=={"total":0,"accepted":0,"not_accepted":0}
summary.update({"adversarial_rejections":9,"empty_view_pass":True,"cold_start_from_unrelated_directory":True})
(OUT/"status.json").write_text(json.dumps(status,indent=2))
(OUT/"proof.json").write_text(json.dumps(summary,indent=2))
print("WORKBENCH_CLI="+json.dumps(summary),flush=True)
