#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from qualification.reduce_evidence import reduce_receipts

ROOT=Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory(prefix="validator-error-") as tmp:
    root=Path(tmp)
    task=root/"task"
    fixture=task/"fixture"
    fixture.mkdir(parents=True)
    (fixture/"value.txt").write_text("PENDING\n")
    (task/"task.json").write_text(json.dumps({
        "schema_version":1,
        "id":"validator-error-fixture",
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
    (task/"verify.py").write_text("raise SystemExit(2)\n")

    candidate=root/"candidate.py"
    candidate.write_text(
        """from pathlib import Path
Path("value.txt").write_text("READY\\n")
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
    proc=subprocess.run([
        sys.executable,str(ROOT/"qualification/run_task.py"),
        "--task-commit","a"*40,
        "--substrate-profile-id","validator-error-fixture",
        "--substrate-profile-commit","b"*40,
        str(task),str(meta),str(receipt),
        "--",sys.executable,str(candidate),
    ],text=True,capture_output=True)
    assert proc.returncode==1,(proc.stdout,proc.stderr)
    row=json.loads(receipt.read_text())
    assert row["observation"]["failure_class"]=="validator-error"
    assert "validator-error" in row["observation"]["failure_signals"]
    assert row["observation"]["workload"]["model_rounds"]==1
    env=reduce_receipts([row])[0]
    assert env["evidence_pattern"]=="NO_TERMINAL_EVIDENCE"
    assert env["evidence"]["incomplete"]==1
    assert env["evidence"]["validated_fail"]==0

print("PASS validator crash remains infrastructure/incomplete evidence")
