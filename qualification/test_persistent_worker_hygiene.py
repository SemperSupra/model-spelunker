#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory(prefix="persistent-hygiene-") as tmp:
    root=Path(tmp)
    task=root/"task"
    fixture=task/"fixture"
    fixture.mkdir(parents=True)
    (fixture/"value.txt").write_text("PENDING\n")
    (task/"task.json").write_text(json.dumps({
        "schema_version":1,
        "id":"persistent-hygiene-fixture",
        "task_class":"software.bounded-repair",
        "instruction":"write READY",
        "fixture":"fixture",
        "verifier":"verify.py",
        "limits":{"wall_seconds":5},
        "success":{"kind":"deterministic-final-state"},
        "demands":{},
        "allowed_write_paths":["value.txt"],
        "projected_tools":["write_file"],
    }))
    (task/"verify.py").write_text(
        """import sys
from pathlib import Path
root=Path(sys.argv[1])
raise SystemExit(0 if root.joinpath("value.txt").read_text()=="READY\\n" else 1)
"""
    )
    candidate=root/"candidate.py"
    candidate.write_text(
        """import os
from pathlib import Path
cwd=Path.cwd()
if Path("contamination.marker").exists():
    raise SystemExit("stale task state visible")
Path("value.txt").write_text("READY\\n")
Path("contamination.marker").write_text("must die with workspace")
with open(os.environ["HYGIENE_CWD_LOG"],"a") as f:
    f.write(str(cwd)+"\\n")
print('MODEL_SPELUNKER_TOOL_CALLS=1')
print('MODEL_SPELUNKER_PROVIDER_OBSERVATIONS=[{"requested_model":"fixture","resolved_model":"fixture"}]')
"""
    )
    meta=root/"candidate.json"
    meta.write_text(json.dumps({
        "harness":{"name":"fixture","version":"1"},
        "model":{"provider":"none","id":"none"},
        "toolset":["write_file"],
    }))
    log=root/"cwd.log"
    env=dict(os.environ)
    env["HYGIENE_CWD_LOG"]=str(log)
    receipts=[]
    for rep in range(3):
        receipt=root/f"receipt-{rep}.json"
        proc=subprocess.run([
            sys.executable,str(ROOT/"qualification/run_task.py"),
            "--task-commit","a"*40,
            "--substrate-profile-id","persistent-hygiene-fixture",
            "--substrate-profile-commit","b"*40,
            str(task),str(meta),str(receipt),
            "--",sys.executable,str(candidate),
        ],text=True,capture_output=True,env=env)
        assert proc.returncode==0,(proc.stdout,proc.stderr)
        receipts.append(json.loads(receipt.read_text()))

    workdirs=[Path(line) for line in log.read_text().splitlines()]
    assert len(workdirs)==3
    assert len(set(workdirs))==3
    assert all(not path.exists() for path in workdirs)
    assert all(row["observation"]["success"] for row in receipts)
    assert len({row["run_id"] for row in receipts})==3

print("PASS repeated reps do not inherit prior task workspace contamination")
