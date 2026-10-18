#!/usr/bin/env python3
"""Contract test: Windows candidate group termination must terminate descendants."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qualification.run_task import _terminate_candidate_group


def pid_is_running(pid: int) -> bool:
    if os.name == "nt":
        check = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in check.stdout
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def test_windows_descendant_termination() -> None:
    # Spawn a parent process that spawns a background child sleeping 60s
    parent_script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(f'CHILD_PID={child.pid}', flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", parent_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    child_pid = None
    assert proc.stdout is not None
    for line in proc.stdout:
        if line.startswith("CHILD_PID="):
            child_pid = int(line.strip().split("=")[1])
            break

    assert child_pid is not None, "Failed to capture child PID"
    assert pid_is_running(child_pid), f"Child PID {child_pid} should be running"

    # Terminate the candidate group
    _terminate_candidate_group(proc)

    # Allow brief window for OS process cleanup
    time.sleep(0.5)

    assert proc.poll() is not None, "Parent process must be terminated"
    assert not pid_is_running(child_pid), f"Child process {child_pid} must be terminated by group cleanup"
    print("PASS Windows descendant-process cleanup terminated parent and child")


if __name__ == "__main__":
    test_windows_descendant_termination()
