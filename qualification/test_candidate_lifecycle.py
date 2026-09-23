#!/usr/bin/env python3
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

from qualification.run_task import run_candidate_process


if os.name != "posix":
    print("SKIP process-group lifecycle test: POSIX only")
    raise SystemExit(0)

with tempfile.TemporaryDirectory(prefix="model-spelunker-lifecycle-") as tmp:
    root=Path(tmp)
    pid_file=root/"child.pid"
    candidate=root/"candidate.py"
    candidate.write_text(
        """import os, subprocess, sys, time
pid_file=sys.argv[1]
child=subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(pid_file, "w").write(str(child.pid))
print("spawned", child.pid, flush=True)
time.sleep(60)
""",
        encoding="utf-8",
    )
    rc, stdout, stderr, timed_out = run_candidate_process(
        [sys.executable, str(candidate), str(pid_file)],
        cwd=root,
        input_text="",
        timeout=1,
        env=dict(os.environ),
    )
    assert timed_out is True
    assert rc == 124
    assert pid_file.exists(), (stdout, stderr)
    child_pid=int(pid_file.read_text())

    deadline=time.time()+3
    while time.time()<deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise AssertionError(f"orphan candidate child survived timeout: pid={child_pid}")

print("PASS candidate timeout kills the process group")


with tempfile.TemporaryDirectory(prefix="model-spelunker-lifecycle-normal-") as tmp:
    root=Path(tmp)
    pid_file=root/"child.pid"
    candidate=root/"candidate.py"
    candidate.write_text(
        """import subprocess, sys
child=subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(sys.argv[1], "w").write(str(child.pid))
print("done", flush=True)
"""
    )
    rc, stdout, stderr, timed_out = run_candidate_process(
        [sys.executable, str(candidate), str(pid_file)],
        cwd=root,
        input_text="",
        timeout=5,
        env=dict(os.environ),
    )
    assert timed_out is False
    assert rc == 0
    child_pid=int(pid_file.read_text())
    deadline=time.time()+3
    while time.time()<deadline:
        try:
            os.kill(child_pid,0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        try:
            os.kill(child_pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise AssertionError(f"background child survived successful candidate exit: pid={child_pid}")

print("PASS successful candidates cannot leave background children")
