"""Actual browser/CLI plan-preview parity and intent supersession, no execution."""
import hashlib,json,pathlib,subprocess,sys
from playwright.sync_api import sync_playwright
here=pathlib.Path(__file__).resolve().parent
out=pathlib.Path(sys.argv[1]).resolve();out.mkdir()
receipts=out/"receipts";receipts.mkdir()
def digest(x):return "sha256:"+hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def write(p,x):p.write_text(json.dumps(x),encoding="utf-8")
i={"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","revision":1,"objective":"Framework proving only","allowed_engines":["cpu"],"max_trials":12}
s={"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","intent_digest":digest(i),"treatments":[{"engine":"cpu","memory":"off","retrieval":None},{"engine":"cpu","memory":"on","retrieval":2}],"repetitions":3}
ip=out/"intent.json";sp=out/"spec.json"
def run(*args):
    p=subprocess.run([sys.executable,str(here/"workbench.py"),*map(str,args)],cwd=out,capture_output=True,text=True,timeout=15)
    assert p.returncode==0,p.stderr
    return json.loads(p.stdout)
rows=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for n in range(3):
        revised={**i,"revision":2+n,"max_trials":4}
        for label,intent,spec,want in [("original",i,s,[]),("stale",revised,s,["STALE_INTENT","BUDGET_EXCEEDED"]),("revised",revised,{**s,"intent_digest":digest(revised),"repetitions":2},[])]:
            write(ip,intent);write(sp,spec)
            args=["--receipts",receipts,"--intent",ip,"--spec",sp]
            state=run("status",*args);review=state["plan_review"]
            assert [f["code"] for f in review["findings"]]==want
            assert review["execution_authorized"] is False and review["promotion_authorized"] is False
            html=out/(f"{n}-{label}.html");run("render",*args,"--output",html)
            page=browser.new_page(viewport={"width":390 if n%2==0 else 1440,"height":850})
            page.goto(html.as_uri())
            assert json.loads(page.locator("#snapshot").text_content())==state
            assert page.locator("#plan-status").inner_text()==review["preview_status"]
            assert page.locator("#plan-findings li").count()==len(want)
            assert "not authorized" in page.locator("#plan-authority").inner_text()
            rows.append({"rep":n,"case":label,"status":review["preview_status"],"findings":want})
            if n==0:page.screenshot(path=str(out/(label+".png")),full_page=True)
            page.close()
    browser.close()
summary={"scope":"FRAMEWORK_PROVING_ONLY","controls":len(rows),"parity":len(rows),"cases":rows,"authorization_granted":False}
write(out/"summary.json",summary);print("WORKBENCH_PLAN="+json.dumps(summary),flush=True)
