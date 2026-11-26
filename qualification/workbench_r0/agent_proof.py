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
reference_system="You are a limited public-synthetic file reader. Work only in the disposable current task directory. First read index.txt, then read the TARGET file. Do not guess file contents, use shell commands, search external files, write data or describe unperformed actions. The session is headless and only the read_file tool is available. After reading index.txt and its TARGET file, return only the VALUE line from the selected TARGET file. Do not return index text.\n"
evidence_system=system.read_text()
def diagnostics(stdout,work):
    # Preserve shape and error category rather than raw response text or paths.
    try: frames=json.loads(stdout)
    except ValueError:return {"format":"INVALID_JSON","events":[]}
    if not isinstance(frames,list):return {"format":"INVALID_SHAPE","events":[]}
    events=[]
    for frame in frames:
        if not isinstance(frame,dict):continue
        msg=frame.get("message")
        if not isinstance(msg,dict):continue
        blocks=msg.get("content")
        if not isinstance(blocks,list):continue
        for item in blocks:
            if not isinstance(item,dict):continue
            kind=item.get("type")
            if kind=="tool_use":
                args=item.get("input") or {}
                paths=[args.get(k) for k in ("absolute_path","file_path","path") if k in args] if isinstance(args,dict) else []
                target="INVALID_PATH"
                if len(paths)==1 and isinstance(paths[0],str):
                    p=pathlib.Path(paths[0]);p=(p if p.is_absolute() else work/p).resolve()
                    try:
                        rel=p.relative_to(work.resolve()).as_posix()
                        target=rel if rel in ("index.txt","a.txt","b.txt") else "OTHER_IN_WORKCELL"
                    except ValueError:target="OUTSIDE_WORKCELL"
                events.append({"kind":kind,"tool":item.get("name") if item.get("name")=="read_file" else "OTHER","target":target,"path_style":"absolute" if paths and isinstance(paths[0],str) and pathlib.Path(paths[0]).is_absolute() else "relative_or_missing"})
            elif kind=="tool_result":
                flag=item.get("is_error")
                content=json.dumps(item.get("content",""),ensure_ascii=True).lower()
                categories=[label for label,terms in [("not_found",("enoent","not found","does not exist","no such file")),("scope",("outside","not within","workspace","not allowed")),("permission",("permission","denied","approval")),("argument",("invalid argument","absolute path","required","parameter"))] if any(t in content for t in terms)]
                events.append({"kind":kind,"error_flag":"MISSING" if "is_error" not in item else flag if type(flag) is bool else "INVALID","categories":categories})
    return {"format":"JSON_ARRAY","events":events}

try:
    for block in range(2):
        selected=rows[block];decoy=rows[2]
        expect=selected["native_phase"]["request_id"];wrong=decoy["native_phase"]["request_id"]
        order=["reference","json_original","line_original","json_sequential","line_sequential"] if block==0 else ["line_sequential","json_sequential","line_original","json_original","reference"]
        target=rng.choice(["a.txt","b.txt"])
        for arm in order:
            work=temp/f"workbench-agent-{block}-{arm}";work.mkdir()
            (work/"index.txt").write_text("TARGET="+target+"\n")
            sequential=arm.endswith("_sequential")
            system.write_text(reference_system if arm=="reference" else evidence_system + (" Wait for the result of the index read before issuing the second read. The TARGET value is the entire filename; never append an extension or treat a request ID as a filename. After the second successful read, stop using tools and return the exact request_id.\n" if sequential else ""))
            expected=("VALUE="+expect.removeprefix("req-")) if arm=="reference" else expect
            decoy_value=("VALUE="+wrong.removeprefix("req-")) if arm=="reference" else wrong
            for name,row in [(target,selected),("b.txt" if target=="a.txt" else "a.txt",decoy)]:
                actual=cli("evidence",*args,"--run-id",row["run_id"])
                payload= {"run_id":actual["run_id"],"request_id":actual["native_phase"]["request_id"],"scope":actual["purpose"],"receipt_sha256":actual["receipt_sha256"]}
                text=("VALUE="+actual["native_phase"]["request_id"].removeprefix("req-")) if arm=="reference" else "\n".join(f"{k}={payload[k]}" for k in sorted(payload)) if arm.startswith("line_") else json.dumps(payload,sort_keys=True,separators=(",",":"))
                (work/name).write_text(text+"\n")
            cmd=["timeout","150",str(cell/"native/qwen-code/bin/qwen"),"--prompt",("Use read_file on index.txt. Its TARGET names a second file; read that file using read_file and output only its VALUE. Do not guess." if arm=="reference" else "Read index.txt, then the TARGET file using read_file. Output only the exact request_id from that file. Do not guess."),"--model","qwen3:1.7b","--core-tools","read_file","--approval-mode","default","--max-session-turns","4","--max-tool-calls","4","--max-wall-time","140s","--output-format","json"]
            before=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.monotonic()
            p=subprocess.run(cmd,cwd=work,env=env,capture_output=True,text=True,errors="replace",timeout=160)
            elapsed=time.monotonic()-start;after=resource.getrusage(resource.RUSAGE_CHILDREN)
            lineage=lineage_verdict(p.stdout,work,target);final=classify_final(p.stdout,expected,decoy_value);drift=audit(cfg)
            diag=diagnostics(p.stdout,work)
            events=diag["events"]
            causal=[x["kind"] for x in events]==["tool_use","tool_result","tool_use","tool_result"] and lineage=="PASS"
            good=p.returncode==0 and causal and verify_selected(p.stdout,expected,decoy_value) and drift["byte_identical"]
            observations.append({"block":block,"arm":arm,"run_id":selected["run_id"],"input_file_bytes":(work/target).stat().st_size,"wall_seconds":elapsed,"harness_waited_cpu_seconds":after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,"server_cpu_seconds":None,"native_token_counts":None,"exit":p.returncode,"lineage":lineage,"final":final,"settings_identical":drift["byte_identical"],"accepted":good,"causal_sequence":causal,"diagnostics":diag,"stdout_sha256":hashlib.sha256(p.stdout.encode()).hexdigest()})
    assert len(observations)==10
    summary={"scope":"FRAMEWORK_PROVING_ONLY","harness":"Qwen Code 0.28.3","reference_source":"a0426d62e282ab24199fe10097abb400aeb46c01","model":"qwen3:1.7b","setup_wall_seconds":setup,"observations":observations,"accepted_by_arm":{k:sum(x["accepted"] for x in observations if x["arm"]==k) for k in ("reference","json_original","line_original","json_sequential","line_sequential")},"limitations":"two counterbalanced blocks, 2x2 compact JSON vs key-value lines and original vs explicit sequential system guidance; same fields and exact expected request_id; separate reference VALUE arm. Strict causal sequencing added, previous lineage and final retained. Actual read_file consumption only, not autonomous CLI invocation. No inference CPU/native tokens or promotion"}
    (out/"summary.json").write_text(json.dumps(summary,indent=2))
    print("AGENT_WORKBENCH="+json.dumps(summary),flush=True)
finally:
    run([sys.executable,emb,"remove","--root",cell])
