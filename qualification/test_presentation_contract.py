#!/usr/bin/env python3
from __future__ import annotations
import copy
import hashlib
import json
from qualification.human_io.presentation_contract import check, project

task={"id":"session-1","revision":4,"task_sha256":hashlib.sha256(b"fixed task").hexdigest()}
def profile(width,height,display_count,inputs,outputs=("text",),font_scale=1.0):
    return {"schema":"actor-presentation-capabilities/v1",
      "displays":[{"width":width,"height":height,"scale":1.0,"primary":i==0}
                  for i in range(display_count)],
      "viewport":{"width":width,"height":height,"font_scale":font_scale,"reduced_motion":False},
      "inputs":list(inputs),"outputs":list(outputs),
      "preferences":{"mode":"auto","density":"auto","speech_enabled":True,"details_on_demand":True},
      "observation":"synthetic"}

def fails(action):
    try: action()
    except (ValueError,KeyError,TypeError):return
    raise AssertionError("invalid presentation/authority accepted")

def main():
    mobile=profile(390,844,1,("touch","voice"),("text","speech"))
    tablet=profile(900,1200,1,("touch","pen"),("text","visual"))
    workstation=profile(2560,1440,3,("keyboard","pointer","pen"),("text","visual"))
    projections=[project(x,task) for x in (mobile,tablet,workstation)]
    assert [x["tier"] for x in projections]==["compact","balanced","workspace"]
    assert [x["layout"]["panes"] for x in projections]==[1,2,4]
    assert projections[0]["speech_suggested"] is True
    assert projections[2]["speech_suggested"] is False
    assert all(x["details_available"] and not x["hidden_task_content"] for x in projections)
    assert all(x["session"]==task and not x["authorization_changed"]
               and not x["tools_changed"] for x in projections)
    assert projections[0]["layout"]["controls"]=="large-targets"
    assert project(profile(1000,700,1,("keyboard",),font_scale=2.0),task)["tier"]=="compact"
    p=copy.deepcopy(mobile);p["preferences"]["mode"]="detail"
    assert project(p,task)["default_mode"]=="detail"
    assert project(p,task)["tier"]=="compact"
    cases=[
      lambda: project({**mobile,"permission":"grant"},task),
      lambda: project({**mobile,"displays":[]},task),
      lambda: project({**mobile,"displays":mobile["displays"]*9},task),
      lambda: project({**mobile,"displays":[{**mobile["displays"][0],"primary":False}]},task),
      lambda: project({**mobile,"viewport":{**mobile["viewport"],"width":0}},task),
      lambda: project({**mobile,"viewport":{**mobile["viewport"],"font_scale":0}},task),
      lambda: project({**mobile,"viewport":{**mobile["viewport"],"reduced_motion":"false"}},task),
      lambda: project({**mobile,"inputs":["keyboard","keyboard"]},task),
      lambda: project({**mobile,"inputs":["fingerprint"]},task),
      lambda: project({**mobile,"outputs":["speech"]},task),
      lambda: project({**mobile,"preferences":{**mobile["preferences"],"mode":"execute-tool"}},task),
      lambda: project({**mobile,"preferences":{**mobile["preferences"],"density":"max-risk"}},task),
      lambda: project(mobile,{**task,"task_sha256":"fake"}),
      lambda: project(mobile,{**task,"revision":-1}),
      lambda: project(mobile,{**task,"approve":True}),
      lambda: project({**mobile,"observation":"real-hil-qualified"},task),
    ]
    for f in cases:fails(f)
    print(json.dumps({"status":"PASS","layouts":[x["tier"] for x in projections],
                      "negative_cases":len(cases),"same_task":True,
                      "execution_or_device_hil":False,"production_admitted":False},sort_keys=True))
if __name__=="__main__":main()
