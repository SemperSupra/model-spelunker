#!/usr/bin/env python3
"""R42 human I/O independent stdlib contract + negative controls."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from qualification.human_io.hid_contract import (
    CHANNELS, SENSITIVE, digest_bytes, inventory_summary, normalize_event,
    validate_profile,
)

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/"human_io"/"platform_candidates.json"

def reject(fn):
    try: fn()
    except (ValueError,KeyError,TypeError): return
    raise AssertionError("unsafe human I/O mutation accepted")

def main():
    raw=json.loads(SOURCE.read_text(encoding="utf-8"))
    assert raw["schema"]=="actor-human-io-candidate-platforms/v1"
    profiles=raw["profiles"]
    assert len(profiles)==10
    assert {p["platform"] for p in profiles}=={
      "windows","macos","linux","android","ios","ipados","server-headless","browser","xr"}
    for p in profiles:
        assert {e["channel"] for e in p["entries"]}==CHANNELS
        assert validate_profile(p)["physical_exercise_claims"]==0
    assert inventory_summary(profiles)["production_admission"]=="NOT_GRANTED"

    p=copy.deepcopy(profiles[0])
    e=next(x for x in p["entries"] if x["channel"]=="keyboard")
    e.update(state="observed",transport="usb-hid",scope="local",
             evidence_sha256=digest_bytes(b"synthetic-receipt-for-validator-test"),
             permission="not-applicable")
    # Synthetic test record is deliberately NOT declared as exercised device HIL.
    r=normalize_event(p,{"channel":"keyboard","intent":"request-approval",
                        "source":"human-device","sequence":2})
    assert r["tool_execution_approved"] is False
    assert r["authorization"]=="UNTRUSTED_INPUT_ONLY"
    # Assistive access can request review but cannot bypass authenticated authorization.
    switch=next(x for x in p["entries"] if x["channel"]=="switch-access")
    switch.update(state="observed",transport="os-accessibility",scope="local",
                  evidence_sha256=digest_bytes(b"synthetic-switch-for-validator-test"),
                  permission="not-applicable")
    assert normalize_event(p,{"channel":"switch-access","intent":"request-approval",
            "source":"assistive-device","sequence":3})["tool_execution_approved"] is False

    cases=[
      lambda: validate_profile({**p,"authority":{**p["authority"],"production_admitted":True}}),
      lambda: validate_profile({**p,"authority":{**p["authority"],"grants_tool_authority":True}}),
      lambda: validate_profile({**p,"authority":{**p["authority"],"allows_injected_human_approval":True}}),
      lambda: validate_profile({**p,"platform":"unsupported"}),
      lambda: validate_profile({**p,"entries":p["entries"]+[p["entries"][0]]}),
      lambda: validate_profile({**p,"entries":[{**v,"state":"exercised","scope":"synthetic"}
              if v["channel"]=="keyboard" else v for v in p["entries"]]}),
      lambda: validate_profile({**p,"entries":[{**v,"state":"observed","evidence_sha256":None}
              if v["channel"]=="keyboard" else v for v in p["entries"]]}),
      lambda: validate_profile({**p,"entries":[{**v,"permission":"granted","state":"unknown"}
              if v["channel"]=="camera" else v for v in p["entries"]]}),
      lambda: normalize_event(p,{"channel":"camera","intent":"attach",
                                "source":"human-device","sequence":4}),
      lambda: normalize_event(p,{"channel":"keyboard","intent":"approve-tool",
                                "source":"human-device","sequence":5}),
      lambda: normalize_event(p,{"channel":"keyboard","intent":"select",
                                "source":"synthetic","sequence":6}),
      lambda: normalize_event(p,{"channel":"keyboard","intent":"select",
                                "source":"human-device","sequence":-1}),
      lambda: normalize_event(p,{"channel":"keyboard","intent":"select",
                                "source":"human-device","sequence":7,"payload":"secret"}),
      lambda: validate_profile({**p,"entries":[{**v,"state":"advertised","evidence_sha256":"0"*64}
              if v["channel"]=="keyboard" else v for v in p["entries"]]}),
    ]
    for f in cases: reject(f)
    print(json.dumps({"status":"PASS","profile_count":len(profiles),
                      "channels_per_profile":len(CHANNELS),
                      "negative_cases":len(cases),
                      "human_input_grants_tool_approval":False,
                      "physical_hid_exercised":False,
                      "network_or_host_access":False},sort_keys=True))
if __name__=="__main__": main()
