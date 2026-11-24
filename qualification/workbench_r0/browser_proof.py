import json,pathlib,sys,time
from playwright.sync_api import sync_playwright
out=pathlib.Path(sys.argv[1]).resolve()
expected=json.loads((out/"status.json").read_text())
rows=expected["runs"]
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for width in (390,900,1440):
        page=browser.new_page(viewport={"width":width,"height":850})
        errors=[];requests=[]
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.on("request",lambda r:requests.append(r.url))
        t=time.perf_counter()
        page.goto((out/"workbench.html").as_uri())
        assert page.locator("#total").inner_text()=="6"
        assert page.locator("#accepted").inner_text()=="3"
        assert page.locator("#rejected").inner_text()=="3"
        assert json.loads(page.locator("#snapshot").text_content())==expected
        for f,count in [("accepted",3),("rejected",3),("all",6)]:
            page.get_by_label("Filter outcome").select_option(f)
            assert page.locator("#rows tr").count()==count
        for row in rows:
            page.get_by_role("button",name="Inspect "+row["run_id"],exact=True).click()
            assert json.loads(page.locator("#detail").inner_text())==row
        for theme in ("dark","light","system"):
            page.get_by_label("Appearance").select_option(theme)
            assert page.locator("html").get_attribute("data-theme")==theme
        assert not errors and all(u.startswith("file:") for u in requests),(errors,requests)
        page.screenshot(path=str(out/("ui-"+str(width)+".png")),full_page=True)
        results.append({"viewport":width,"receipt_parity":len(rows),"filter_checks":3,"appearance_checks":3,"wall_s":time.perf_counter()-t,"page_errors":len(errors),"network_requests":sum(not u.startswith("file:") for u in requests)})
        page.close()
    browser.close()
(out/"browser-proof.json").write_text(json.dumps(results,indent=2))
print("WORKBENCH_BROWSER="+json.dumps(results),flush=True)
