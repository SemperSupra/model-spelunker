"""Portable resource observation proof. Scope is explicit and never silently equivalent.
Linux waited descendants vs Windows root process CPU via GetProcessTimes.
No process-tree attribution on Windows and no hardware inference.
"""
import ctypes,hashlib,json,math,os,pathlib,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[2]
def write(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def measure(cmd):
    start=time.monotonic()
    if sys.platform.startswith("linux"):
        import resource
        before=resource.getrusage(resource.RUSAGE_CHILDREN)
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=60)
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        value=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime
        source="getrusage/RUSAGE_CHILDREN"
        scope="WAITED_CHILD_TREE_CPU"
        rc=p.returncode;err=p.stderr
    elif sys.platform=="win32":
        from ctypes import wintypes
        api=ctypes.WinDLL("kernel32",use_last_error=True).GetProcessTimes
        api.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4;api.restype=wintypes.BOOL
        with subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) as p:
            try:_,err=p.communicate(timeout=60)
            except subprocess.TimeoutExpired:p.kill();p.communicate();raise
            creation,exit_time,kernel,user=(wintypes.FILETIME() for _ in range(4))
            # Popen retains the process handle until its lifetime ends; query after wait.
            if not api(wintypes.HANDLE(int(p._handle)),ctypes.byref(creation),ctypes.byref(exit_time),ctypes.byref(kernel),ctypes.byref(user)):
                raise ctypes.WinError(ctypes.get_last_error())
            def ticks(x):return (x.dwHighDateTime<<32)|x.dwLowDateTime
            value=(ticks(kernel)+ticks(user))/10_000_000
            source="Win32/GetProcessTimes"
            scope="ROOT_PROCESS_CPU_ONLY"
            rc=p.returncode
    else:
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=60)
        value=None;source="UNSUPPORTED";scope="UNKNOWN";rc=p.returncode;err=p.stderr
    return {"cpu_seconds":value,"source":source,"scope":scope,"wall_seconds":time.monotonic()-start},rc,err
def compatible(a,b):
    return a["scope"]==b["scope"] and a["source"]==b["source"] and a["scope"]!="UNKNOWN" and all(type(x["cpu_seconds"]) in (int,float) and math.isfinite(x["cpu_seconds"]) and x["cpu_seconds"]>=0 for x in (a,b))
def main(out):
    out.mkdir();rows=[];commit=os.environ["GITHUB_SHA"]
    for i in range(3):
        d=out/str(i);d.mkdir();meta=d/"candidate.json";exp=d/"experiment.json";receipt=d/"receipt.json"
        write(meta,{"harness":{"name":"portable-measurement-control"},"model":{"id":"none"},"toolset":["write_file"]})
        write(exp,{"schema_version":2,"id":"portable-sensor-r1","task":{"id":"text-repair-v0"},"claim_type":"framework-proving","experimental_role":"control","design_block":i,"primary_responses":["acceptance","cpu_seconds"]})
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,"--substrate-profile-id","framework-"+sys.platform,"--substrate-profile-commit",commit,"--experiment",str(exp),str(ROOT/"qualification/tasks/text-repair-v0"),str(meta),str(receipt),"--",sys.executable,"-c","from pathlib import Path;Path('value.txt').write_bytes(b'READY\\n')"]
        m,rc,err=measure(cmd);assert rc==0,err
        raw=receipt.read_bytes();r=json.loads(raw);assert r["observation"]["success"] is True
        assert m["wall_seconds"]>0
        expected="ROOT_PROCESS_CPU_ONLY" if sys.platform=="win32" else "WAITED_CHILD_TREE_CPU"
        assert m["scope"]==expected and compatible(m,m)
        row={"scope":"FRAMEWORK_PROVING_ONLY","run_id":r["run_id"],"receipt_sha256":"sha256:"+hashlib.sha256(raw).hexdigest(),"measurement":m,"gpu_seconds":None,"energy_joules":None,"accepted":True}
        write(d/"measurement.json",row);rows.append(row)
    assert len({r["run_id"] for r in rows})==3
    m=rows[0]["measurement"]
    assert not compatible(m,{**m,"scope":"ROOT_PROCESS_CPU_ONLY" if m["scope"]!="ROOT_PROCESS_CPU_ONLY" else "WAITED_CHILD_TREE_CPU"})
    assert not compatible(m,{**m,"cpu_seconds":None})
    assert not compatible(m,{**m,"source":"different"})
    result={"scope":"FRAMEWORK_PROVING_ONLY","platform":sys.platform,"actual_receipts":3,"accepted":3,"cpu_accounting_scope":m["scope"],"source":m["source"],"negative_controls":3,"rows":rows,"promotion_authorized":False,"limitations":"Windows root process excludes children; Linux waited child accounting includes descendants where reaped; cross-scope comparison forbidden; no peak memory, device or energy measurement; private CPython process handle dependency for Windows probe"}
    write(out/"summary.json",result);print("PORTABLE_SENSOR="+json.dumps(result),flush=True)
if __name__=="__main__":main(pathlib.Path(sys.argv[1]).resolve())
