"""Actual native Qwen read-only interview of workbench-derived evidence.
Compare full row and compact projection on paired public synthetic cases.
A failed interview is a scientific observation, not a workflow failure.
"""
import hashlib,json,os,pathlib,random,resource,subprocess,sys,time
HERE=pathlib.Path(__file__).resolve().parent
root=pathlib.Path(sys.argv[1]).resolve();ref=pathlib.Path(sys.argv[2]).resolve();out=pathlib.Path(sys.argv[3]).resolve();out.mkdir()
assert os.environ.get("GITHUB_ACTIONS")=="true"
sys.path.insert(0,str(ref/"qualification/agent_embodiment"))
from final_oracle import verify_selected,classify_final
from lineage_oracle import lineage_verdict
from settings_drift import audit
temp=pathlib.Path(os.environ["RUNNER_TEMP"]).resolve()
cell=temp/"workbench-native-actor"
archive=temp/"workbench-qwen-code.tar.gz"
def run(cmd,**kw):
    return subprocess.run([str(x) for x in cmd],check=True,**kw)
def cli(*args):
    return json.loads(subprocess.check_output([sys.executable,str(HERE/"workbench.py"),*map(str,args)],cwd=out,text=True))
args=["--receipts",root/"receipts","--native-bundles",root/"bundles"]
state=cli("status",*args)
rows=state["runs"];assert len(rows)==3
kit=ref/"qualification/qwencode_public/kit.py";emb=ref/"qualification/agent_embodiment/qwen_embody.py"
begin=time.monotonic()
run([sys.executable,kit,"fetch","--platform","linux-x64","--archive",archive])
run([sys.executable,emb,"stage","--root",cell,"--archive",archive])
run([sys.executable,emb,"verify","--root",cell])
setup=time.monotonic()-begin
home=cell/"home";cfg=home/".qwen/settings.json"
system=home/".qwen/lean-system.md"
system.write_text("You are a limited public-synthetic evidence reader. Work only in the current task directory. Read index.txt then the TARGET named there with read_file. Return only the exact request_id string in the target file. Do not guess, use shell, search external files, write files or report unperformed actions. No authority to execute experiments or promote evidence.\n")
env={k:os.environ[k] for k in ("PATH","LANG","LC_ALL","TMPDIR") if k in os.environ}
env.update({"HOME":str(home),"CI":"true","OLLAMA_API_KEY":"ollama","QWEN_TELEMETRY_ENABLED":"false","QWEN_SYSTEM_MD":str(system),"QWEN_WRITE_SYSTEM_MD":"0","QWEN_SYSTEM_IDENTITY_MD":"0"})
rng=random.Random(1397);observations=[]
try:
    for block in range(2):
        selected=rows[block];decoy=rows[2]
        expect=selected["native_phase"]["request_id"];wrong=decoy["native_phase"]["request_id"]
        order=["full","compact"];rng.shuffle(order)
        target=rng.choice(["a.txt","b.txt"])
        for arm in order:
            work=temp/f"workbench-agent-{block}-{arm}";work.mkdir()
            (work/"index.txt").write_text("TARGET="+target+"\n")
            for name,row in [(target,selected),("b.txt" if target=="a.txt" else "a.txt",decoy)]:
                actual=cli("evidence",*args,"--run-id",row["run_id"])
                payload=actual if arm=="full" else {"run_id":actual["run_id"],"request_id":actual["native_phase"]["request_id"],"scope":actual["purpose"],"receipt_sha256":actual["receipt_sha256"]}
                (work/name).write_text(json.dumps(payload,sort_keys=True,separators=(",",":"))+"\n")
            cmd=["timeout","150",str(cell/"native/qwen-code/bin/qwen"),"--prompt","Read index.txt, then the TARGET file using read_file. Output only the exact request_id from that file. Do not guess.","--model","qwen3:1.7b","--core-tools","read_file","--approval-mode","default","--max-session-turns","4","--max-tool-calls","4","--max-wall-time","140s","--output-format","json"]
            before=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.monotonic()
            p=subprocess.run(cmd,cwd=work,env=env,capture_output=True,text=True,errors="replace",timeout=160)
            elapsed=time.monotonic()-start;after=resource.getrusage(resource.RUSAGE_CHILDREN)
            lineage=lineage_verdict(p.stdout,work,target);final=classify_final(p.stdout,expect,wrong);drift=audit(cfg)
            good=p.returncode==0 and lineage=="PASS" and verify_selected(p.stdout,expect,wrong) and drift["byte_identical"]
            observations.append({"block":block,"arm":arm,"run_id":selected["run_id"],"input_file_bytes":(work/target).stat().st_size,"wall_seconds":elapsed,"harness_waited_cpu_seconds":after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,"server_cpu_seconds":None,"native_token_counts":None,"exit":p.returncode,"lineage":lineage,"final":final,"settings_identical":drift["byte_identical"],"accepted":good,"stdout_sha256":hashlib.sha256(p.stdout.encode()).hexdigest()})
    assert len(observations)==4
    summary={"scope":"FRAMEWORK_PROVING_ONLY","harness":"Qwen Code 0.28.3","reference_source":"a0426d62e282ab24199fe10097abb400aeb46c01","model":"qwen3:1.7b","setup_wall_seconds":setup,"observations":observations,"accepted_by_arm":{k:sum(x["accepted"] for x in observations if x["arm"]==k) for k in ("full","compact")},"limitations":"two paired cases; actual read_file consumption of CLI-derived files, not autonomous CLI discovery/invocation; compact projection is experimental; no inference CPU/token accounting from this harness path; no promotion"}
    (out/"summary.json").write_text(json.dumps(summary,indent=2))
    print("AGENT_WORKBENCH="+json.dumps(summary),flush=True)
finally:
    run([sys.executable,emb,"remove","--root",cell])
