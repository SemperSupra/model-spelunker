#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SENTINEL="MODEL_SPELUNKER_SENTINEL_DO_NOT_LEAK_7f3a9c"

with tempfile.TemporaryDirectory(prefix="credential-hygiene-") as tmp:
    root=Path(tmp)
    task=root/"task"
    fixture=task/"fixture"
    fixture.mkdir(parents=True)
    (fixture/"value.txt").write_text("PENDING\n")
    (task/"task.json").write_text(json.dumps({
        "schema_version":1,
        "id":"credential-hygiene-fixture",
        "task_class":"software.bounded-repair",
        "instruction":"consume the referenced credential and write READY",
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

    credential=root/"credential"
    credential.write_text(SENTINEL)
    credential.chmod(0o600)

    candidate=root/"candidate.py"
    candidate.write_text(
        """import os
from pathlib import Path
secret=Path(os.environ["QUALIFICATION_CREDENTIAL_FILE"]).read_text()
assert secret
Path("value.txt").write_text("READY\\n")
print("credential consumed")
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
    receipt=root/"receipt.json"
    diagnostics=root/"diagnostics.json"
    env=dict(os.environ)
    env["QUALIFICATION_CREDENTIAL_FILE"]=str(credential)
    proc=subprocess.run([
        sys.executable,str(ROOT/"qualification/run_task.py"),
        "--task-commit","a"*40,
        "--substrate-profile-id","credential-hygiene-fixture",
        "--substrate-profile-commit","b"*40,
        "--diagnostics",str(diagnostics),
        str(task),str(meta),str(receipt),
        "--",sys.executable,str(candidate),
    ],text=True,capture_output=True,env=env)
    assert proc.returncode==0,(proc.stdout,proc.stderr)

    surfaces=[
        receipt.read_text(),
        diagnostics.read_text(),
        proc.stdout,
        proc.stderr,
        meta.read_text(),
    ]
    assert all(SENTINEL not in surface for surface in surfaces)
    assert json.loads(receipt.read_text())["observation"]["success"] is True
    assert credential.read_text()==SENTINEL

print("PASS file-backed credential content stays out of receipts and diagnostics")
