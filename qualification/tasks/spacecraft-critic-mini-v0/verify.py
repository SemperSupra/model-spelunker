#!/usr/bin/env python3
import json
import sys
import tempfile
from pathlib import Path
EXPECTED={"schema_version":1,"cases":{"SOLAR-INVALID":{"verdict":"INVALID","violation_code":"SOLAR_POWER"},"SOLAR-VALID":{"verdict":"VALID","violation_code":"NONE"}}}
def check(root):
    try:
        f=json.loads((root/"cases.json").read_text(encoding="utf-8"))
        if f["schema_version"] != 1 or f["source_class"] != "synthetic-public-physics-and-governance" or [x["id"] for x in f["cases"]] != list(EXPECTED["cases"]):
            return False
        return json.loads((root/"critic_report.json").read_text(encoding="utf-8"))==EXPECTED
    except (ValueError,KeyError,OSError,TypeError):
        return False
def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        src=json.loads((Path(__file__).parent/"fixture/cases.json").read_text(encoding="utf-8"))
        (root/"cases.json").write_text(json.dumps(src),encoding="utf-8")
        (root/"critic_report.json").write_text(json.dumps(EXPECTED),encoding="utf-8")
        assert check(root)
        bad=json.loads(json.dumps(EXPECTED));bad["cases"]["SOLAR-INVALID"]={"verdict":"VALID","violation_code":"NONE"}
        (root/"critic_report.json").write_text(json.dumps(bad),encoding="utf-8")
        assert not check(root)
    print("PASS spacecraft-critic-mini-v0 verifier plus rejection control")
if __name__=="__main__":
    if len(sys.argv)==2 and sys.argv[1]=="--self-test":selftest()
    elif len(sys.argv)==2:raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
    else:raise SystemExit(2)
