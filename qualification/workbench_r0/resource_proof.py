import json,pathlib,subprocess,sys,shutil,copy
from playwright.sync_api import sync_playwright
out=pathlib.Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
root=pathlib.Path(__file__).resolve().parents[2]; here=pathlib.Path(__file__).resolve().parent
subprocess.run([sys.executable,str(root/"qualification/resource_join_r0/prove.py"),"proof",str(out/"measured")],check=True)
receipts=out/"receipts";resources=out/"resources";receipts.mkdir();resources.mkdir()
for p in sorted((out/"measured").glob("*-*/receipt.json")):
    shutil.copyfile(p,receipts/(p.parent.name+".json"));shutil.copyfile(p.parent/"resource.json",resources/(p.parent.name+".json"))
def cli(*args,ok=True):
    p=subprocess.run([sys.executable,str(here/"workbench.py"),*map(str,args)],capture_output=True,text=True,cwd=out)
    assert (p.returncode==0)==ok,(p.returncode,p.stdout,p.stderr)
    return json.loads(p.stdout) if ok else json.loads(p.stderr)
args=["--receipts",receipts,"--resources",resources]
s=cli("status",*args);assert s["summary"]=={"total":9,"accepted":6,"not_accepted":3}
truth=json.loads((out/"measured/summary.json").read_text())
assert abs(s["resources"]["cpu_seconds"]-truth["all_attempt_cpu_seconds"])<1e-9
assert abs(s["resources"]["cpu_seconds_per_accepted"]-truth["all_attempt_cpu_seconds_per_accepted"])<1e-9
for r in s["runs"]:assert cli("evidence",*args,"--run-id",r["run_id"])==r
html=out/"resource.html";cli("render",*args,"--output",html)
with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    for width in (390,1440):
        page=b.new_page(viewport={"width":width,"height":850});page.goto(html.as_uri())
        assert json.loads(page.locator("#snapshot").text_content())==s
        assert page.locator("#cpu").inner_text()==format(s["resources"]["cpu_seconds"],".3f")
        assert page.locator("#gpu").inner_text()=="UNKNOWN"
        assert page.locator("#coverage").inner_text()=="9 of 9 receipts have resource evidence"
        page.screenshot(path=str(out/("resource-"+str(width)+".png")),full_page=True);page.close()
    b.close()
# Partial coverage must suppress total, not silently count missing resource as zero.
files=sorted(resources.glob("*.json"));p=files[0];raw=p.read_bytes();p.unlink()
partial=cli("status",*args);assert partial["resources"]["covered"]==8 and partial["resources"]["cpu_seconds"] is None
p.write_bytes(raw)
original=json.loads(raw)
for changes in ("unit","digest","unknown","orphan","duplicate"):
    row=copy.deepcopy(original)
    if changes=="unit":row["metrics"]["cpu_seconds"]["unit"]="ms"
    elif changes=="digest":row["receipt_sha256"]="wrong"
    elif changes=="unknown":row["metrics"]["gpu_seconds"]["value"]=0
    elif changes=="orphan":row["run_id"]="missing"
    q=resources/"negative.json" if changes=="duplicate" else p
    q.write_text(json.dumps(row));assert cli("status",*args,ok=False)["error"]=="INVALID_INPUT"
    if changes=="duplicate":q.unlink()
    else:p.write_bytes(raw)
summary={"scope":"FRAMEWORK_PROVING_ONLY","actual_receipts":9,"cli_parity":9,"browser_parity":2,"partial_coverage_suppressed":True,"negative_controls":5,"resource_totals":s["resources"]}
(out/"integration.json").write_text(json.dumps(summary,indent=2));print("WORKBENCH_RESOURCE="+json.dumps(summary),flush=True)
