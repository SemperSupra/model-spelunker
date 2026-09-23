#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PACKET=ROOT/"qualification/launch-packets/contract-portability-gha-v1.json"
BASE=json.loads(PACKET.read_text())


def run(packet: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w",suffix=".json",delete=False) as handle:
        json.dump(packet,handle)
        path=Path(handle.name)
    try:
        return subprocess.run([
            sys.executable,str(ROOT/"qualification/validate_portable_launch_packet.py"),
            str(path),
            "--task-dir","qualification/tasks/text-repair-v0",
            "--actor-profile","qualification/actors/contract-test-portable.json",
            "--substrate-profile","qualification/fixtures/substrate-profile-gha-v2.json",
        ],cwd=ROOT,text=True,capture_output=True)
    finally:
        path.unlink(missing_ok=True)


assert run(BASE).returncode==0

changed_task=deepcopy(BASE)
changed_task["task"]["package_digest"]="sha256:"+"0"*64
proc=run(changed_task)
assert proc.returncode!=0
assert "task package digest mismatch" in (proc.stderr+proc.stdout)

missing_tool=deepcopy(BASE)
missing_tool["authority"]["tool_refs"]=["tool:write_file"]
proc=run(missing_tool)
assert proc.returncode!=0
assert "tool refs disagree" in (proc.stderr+proc.stdout)

stale_substrate=deepcopy(BASE)
stale_substrate["substrate"]["profile_digest"]="sha256:"+"1"*64
proc=run(stale_substrate)
assert proc.returncode!=0
assert "substrate profile digest mismatch" in (proc.stderr+proc.stdout)

venue_coupled=deepcopy(BASE)
venue_coupled["outputs"]["receipt"]="GITHUB_WORKSPACE/receipt.json"
proc=run(venue_coupled)
assert proc.returncode!=0

print("PASS launch-packet task/tool/substrate/venue fault injection")
