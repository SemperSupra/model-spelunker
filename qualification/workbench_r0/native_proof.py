"""Actual native #385 evidence through same workbench CLI and real browser."""
import copy,json,pathlib,shutil,subprocess,sys
from playwright.sync_api import sync_playwright
here=pathlib.Path(__file__).resolve().parent
source=pathlib.Path(sys.argv[1]).resolve();out=pathlib.Path(sys.argv[2]).resolve();out.mkdir()
receipts=out/"receipts";bundles=out/"bundles";receipts.mkdir();bundles.mkdir()
for d in sorted(p for p in source.iterdir() if p.is_dir()):
    shutil.copytree(d,bundles/d.name);shutil.copyfile(d/"receipt.json",receipts/(d.name+".json"))
def cli(*args,ok=True):
    p=subprocess.run([sys.executable,str(here/"workbench.py"),*map(str,args)],cwd=out,capture_output=True,text=True,timeout=30)
    assert (p.returncode==0)==ok,(p.returncode,p.stdout,p.stderr)
    return json.loads(p.stdout if ok else p.stderr)
args=["--receipts",receipts,"--native-bundles",bundles]
state=cli("status",*args);assert state["native_phase"]["covered"]==3
for row in state["runs"]:
    assert cli("evidence",*args,"--run-id",row["run_id"])==row
    assert row["native_phase"]["metrics"]["prompt_tokens"]>0
    assert row["native_phase"]["cached_tokens"] is None
html=out/"native.html";cli("render",*args,"--output",html)
with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    for width in (390,1440):
        page=b.new_page(viewport={"width":width,"height":850});page.goto(html.as_uri())
        assert json.loads(page.locator("#snapshot").text_content())==state
        assert page.locator("#native-rows tr").count()==3
        assert page.locator("#native-coverage").inner_text()=="3 of 3 receipts have native phase evidence"
        for idx,row in enumerate(state["runs"]):
            cells=page.locator("#native-rows tr").nth(idx).locator("td")
            assert cells.nth(1).inner_text()==str(row["native_phase"]["metrics"]["prompt_tokens"])
            assert cells.nth(4).inner_text()==format(row["native_phase"]["decode_tps"],".2f")
        page.screenshot(path=str(out/f"native-{width}.png"),full_page=True);page.close()
    b.close()
# Partial coverage remains visible and does not fabricate rates.
d=sorted(bundles.iterdir())[0];moved=out/"removed";d.rename(moved)
partial=cli("status",*args);assert partial["native_phase"]["covered"]==2
assert sum("native_phase" not in r for r in partial["runs"])==1
moved.rename(d)
phase=d/"phase.json";raw=phase.read_bytes()
for k in ("request_id","model_digest","output_sha256","packet_digest"):
    x=json.loads(raw);x[k]="wrong";phase.write_text(json.dumps(x))
    assert cli("status",*args,ok=False)["error"]=="INVALID_INPUT"
    phase.write_bytes(raw)
shutil.copytree(d,bundles/"duplicate")
assert cli("status",*args,ok=False)["error"]=="INVALID_INPUT"
shutil.rmtree(bundles/"duplicate")
summary={"scope":"FRAMEWORK_PROVING_ONLY","actual_native_receipts":3,"cli_parity":3,"browser_viewports":2,"partial_coverage":True,"negative_controls":5,"accepted":state["summary"]["accepted"],"promotion_authorized":False}
(out/"summary.json").write_text(json.dumps(summary,indent=2));print("NATIVE_WORKBENCH="+json.dumps(summary),flush=True)
