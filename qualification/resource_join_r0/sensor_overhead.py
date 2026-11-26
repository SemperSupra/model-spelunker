"""Measure observation overhead with the actual canonical task runner.
Linux /proc snapshots are sparse observations, not continuous peak or exclusive attribution.
No persistent collector or target-hardware access.
"""
import hashlib,json,os,pathlib,random,resource,subprocess,sys,threading,time
ROOT=pathlib.Path(__file__).resolve().parents[2]
from prove import write
def snapshot(pid):
    pending=[pid];seen=set();rss=0;observed=0
    while pending and len(seen)<64:
        p=pending.pop()
        if p in seen:continue
        seen.add(p)
        try:
            data=pathlib.Path(f"/proc/{p}/status").read_text()
            line=next((x for x in data.splitlines() if x.startswith("VmRSS:")),None)
            if line is not None:rss+=int(line.split()[1])*1024;observed+=1
            children=pathlib.Path(f"/proc/{p}/task/{p}/children").read_text().split()
            pending.extend(int(x) for x in children)
        except (OSError,ValueError):pass
    return {"processes_with_rss":observed,"summed_rss_bytes":rss if observed else None,"truncated":bool(pending)}
def trial(out,block,workload,interval):
    out.mkdir();commit=os.environ["GITHUB_SHA"]
    meta=out/"candidate.json";write(meta,{"harness":{"name":"synthetic-sensor-control"},"model":{"id":"none"},"toolset":["write_file"],"workload":workload})
    exp=out/"experiment.json";write(exp,{"schema_version":2,"id":"sensor-overhead-r1","task":{"id":"text-repair-v0"},"claim_type":"framework-proving","experimental_role":"control","design_block":block,"primary_responses":["acceptance","cpu_seconds","wall_seconds"]})
    receipt=out/"receipt.json";loops=10000 if workload=="short" else 1400000
    code=f"from pathlib import Path;import hashlib;x=b'x'\nfor _ in range({loops}):x=hashlib.sha256(x).digest()\nPath('value.txt').write_bytes(b'READY\\n')"
    cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,"--substrate-profile-id","framework-public-linux","--substrate-profile-commit",commit,"--experiment",str(exp),str(ROOT/"qualification/tasks/text-repair-v0"),str(meta),str(receipt),"--",sys.executable,"-c",code]
    before=resource.getrusage(resource.RUSAGE_CHILDREN);cpu0=time.process_time();start=time.monotonic()
    stop=threading.Event();samples=[];sensor_cpu=[]
    with (out/"stdout.txt").open("w") as stdout,(out/"stderr.txt").open("w") as stderr:
        proc=subprocess.Popen(cmd,cwd=ROOT,stdout=stdout,stderr=stderr)
        def sensor():
            t0=time.thread_time()
            while not stop.is_set():
                samples.append({"elapsed_s":time.monotonic()-start,**snapshot(proc.pid)})
                if stop.wait(interval):break
            sensor_cpu.append(time.thread_time()-t0)
        worker=None
        if interval is not None:
            worker=threading.Thread(target=sensor);worker.start()
        try:proc.wait(timeout=60)
        except subprocess.TimeoutExpired:proc.kill();proc.wait();raise
        finally:
            stop.set()
            if worker is not None:worker.join()
    after=resource.getrusage(resource.RUSAGE_CHILDREN);elapsed=time.monotonic()-start;parent_cpu=time.process_time()-cpu0
    assert receipt.exists()
    raw=receipt.read_bytes();r=json.loads(raw);assert r["observation"]["success"] is True and proc.returncode==0
    child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime
    valid=[x["summed_rss_bytes"] for x in samples if x["summed_rss_bytes"] is not None]
    row={"scope":"FRAMEWORK_PROVING_ONLY","block":block,"workload":workload,"interval_ms":None if interval is None else int(interval*1000),"run_id":r["run_id"],"receipt_sha256":"sha256:"+hashlib.sha256(raw).hexdigest(),"accepted":True,"child_cpu_seconds":child_cpu,"observer_process_cpu_seconds":parent_cpu,"sampler_thread_cpu_seconds":sensor_cpu[0] if sensor_cpu else None,"total_measured_cpu_seconds":child_cpu+parent_cpu,"wall_seconds":elapsed,"samples":len(samples),"samples_with_rss":len(valid),"max_sampled_summed_rss_bytes":max(valid) if valid else None,"truncated_samples":sum(x["truncated"] for x in samples)}
    if interval is None:assert not samples and row["max_sampled_summed_rss_bytes"] is None
    else:assert samples and sensor_cpu
    write(out/"samples.json",samples);write(out/"measurement.json",row)
    return row
def main(out):
    out.mkdir();rows=[];rng=random.Random(1412)
    for block in range(3):
        cells=[(workload,interval) for workload in ("short","long") for interval in (None,.005,.02,.1)];rng.shuffle(cells)
        for workload,interval in cells:rows.append(trial(out/f"{block}-{workload}-{interval}",block,workload,interval))
    assert len(rows)==24 and len({r["run_id"] for r in rows})==24
    groups={}
    for workload in ("short","long"):
        groups[workload]={}
        for interval in (None,5,20,100):
            v=[r for r in rows if r["workload"]==workload and r["interval_ms"]==interval]
            assert len(v)==3
            groups[workload][str(interval)]={"accepted":3,"cpu_seconds":sum(r["total_measured_cpu_seconds"] for r in v),"wall_seconds":sum(r["wall_seconds"] for r in v),"sampler_thread_cpu_seconds":sum(r["sampler_thread_cpu_seconds"] or 0 for r in v) if interval is not None else None,"samples":sum(r["samples"] for r in v),"samples_with_rss":sum(r["samples_with_rss"] for r in v)}
    result={"scope":"FRAMEWORK_PROVING_ONLY","attempts":24,"accepted":24,"paired_blocks":3,"groups":groups,"rows":rows,"promotion_authorized":False,"limitations":"one public Linux runner; proc children snapshots may miss short processes, summed RSS double-counts shared pages and is not actual peak or PSS; sampler thread CPU included in observer process CPU, not added again; no GPU/energy measurement or target sampling recommendation"}
    write(out/"summary.json",result);print("SENSOR_OVERHEAD="+json.dumps({k:v for k,v in result.items() if k!="rows"}),flush=True)
if __name__=="__main__":main(pathlib.Path(sys.argv[1]).resolve())
