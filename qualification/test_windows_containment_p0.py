#!/usr/bin/env python3
"""P0 Causal Falsification Tests: Windows Process Tree Containment (PROC-01, PROC-02, PROC-03, PROC-04)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qualification.run_task import run_candidate_process
from qualification.windows_containment import WindowsJobObject


def test_proc_01_parent_exits_while_descendants_live() -> None:
    """PROC-01: Parent process exits immediately while background descendants sleep.
    Job Object containment must kill all surviving descendants when parent/job finishes.
    """
    if os.name != "nt":
        print("SKIP: PROC-01 requires Windows NT")
        return

    with tempfile.TemporaryDirectory() as td:
        pid_file = Path(td) / "descendant.pid"
        marker_file = Path(td) / "still_alive.marker"

        descendant_code = f"""
import os, time
with open({repr(str(pid_file))}, "w") as f:
    f.write(str(os.getpid()))
for _ in range(60):
    time.sleep(1)
    with open({repr(str(marker_file))}, "w") as f:
        f.write("alive")
"""

        parent_code = f"""
import os, subprocess, sys, time
p = subprocess.Popen([sys.executable, "-c", {repr(descendant_code)}])
for _ in range(50):
    if os.path.exists({repr(str(pid_file))}):
        break
    time.sleep(0.1)
sys.exit(0)
"""

        exit_code, stdout, stderr, timed_out = run_candidate_process(
            [sys.executable, "-c", parent_code],
            cwd=Path(td),
            input_text="",
            timeout=10,
            env=dict(os.environ),
        )

        assert exit_code == 0, f"Parent should exit 0, got {exit_code}"
        assert not timed_out, "Parent should not time out"

        # Wait up to 5s for descendant to have written its PID
        for _ in range(50):
            if pid_file.exists():
                break
            time.sleep(0.1)

        assert pid_file.exists(), "Descendant PID was not recorded"
        descendant_pid = int(pid_file.read_text().strip())

        # Allow cleanup to complete
        time.sleep(1.0)

        # Assert descendant is terminated
        check = subprocess.run(["tasklist", "/FI", f"PID eq {descendant_pid}"], capture_output=True, text=True)
        assert str(descendant_pid) not in check.stdout, f"Descendant PID {descendant_pid} survived parent exit!"

    print("PASS: PROC-01 Parent-exits-first descendant cleanup")


def test_proc_02_nested_runtime_breakaway_attempt() -> None:
    """PROC-02: Nested processes attempt breakaway (e.g. CREATE_BREAKAWAY_FROM_JOB).
    WindowsJobObject must prevent uncontained escape and terminate all descendants.
    """
    if os.name != "nt":
        print("SKIP: PROC-02 requires Windows NT")
        return

    with tempfile.TemporaryDirectory() as td:
        pid_file = Path(td) / "breakaway.pid"

        # Child tries to spawn grandchild with CREATE_BREAKAWAY_FROM_JOB (0x01000000)
        # Without JOB_OBJECT_LIMIT_BREAKAWAY_OK, Windows denies breakaway and keeps child inside job
        child_code = f"""
import os, subprocess, sys, time
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
try:
    p = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=CREATE_BREAKAWAY_FROM_JOB,
    )
    with open({repr(str(pid_file))}, "w") as f:
        f.write(str(p.pid))
except Exception:
    # If breakaway denied by OS, spawn normal descendant
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    with open({repr(str(pid_file))}, "w") as f:
        f.write(str(p.pid))
time.sleep(60)
"""

        exit_code, stdout, stderr, timed_out = run_candidate_process(
            [sys.executable, "-c", child_code],
            cwd=Path(td),
            input_text="",
            timeout=3,  # Force timeout
            env=dict(os.environ),
        )

        assert timed_out, "Run should time out"
        assert exit_code == 124

        # Read grandchild PID if written
        if pid_file.exists():
            grandchild_pid = int(pid_file.read_text().strip())
            time.sleep(1.0)
            check = subprocess.run(["tasklist", "/FI", f"PID eq {grandchild_pid}"], capture_output=True, text=True)
            assert str(grandchild_pid) not in check.stdout, f"Grandchild PID {grandchild_pid} survived breakaway attempt!"

    print("PASS: PROC-02 Nested runtime breakaway containment")


def test_proc_03_stdin_write_and_close_failure() -> None:
    """PROC-03: Candidate exits immediately with broken pipe on stdin write.
    Cleanup must run unconditionally and cleanly terminate candidate resources.
    """
    with tempfile.TemporaryDirectory() as td:
        # Child exits immediately with non-zero exit code, closing stdin pipe before write
        child_code = "import sys; sys.exit(42)"

        exit_code, stdout, stderr, timed_out = run_candidate_process(
            [sys.executable, "-c", child_code],
            cwd=Path(td),
            input_text="A" * 100000,  # Large input to trigger BrokenPipeError
            timeout=10,
            env=dict(os.environ),
        )

        assert exit_code == 42, f"Expected child exit code 42, got {exit_code}"
        assert not timed_out

    print("PASS: PROC-03 Stdin write failure bounded cleanup")


def test_proc_04_job_object_lifecycle_and_diagnostics() -> None:
    """PROC-04: WindowsJobObject instantiation, assignment, and termination lifecycle."""
    if os.name != "nt":
        print("SKIP: PROC-04 requires Windows NT")
        return

    with WindowsJobObject() as job:
        assert job.handle is not None and job.handle != 0
        p = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        job.assign_process(int(p._handle))
        job.terminate(99)
        p.wait(timeout=5)
        assert p.poll() is not None, "Process should be terminated by job object"

    print("PASS: PROC-04 Job Object lifecycle and diagnostics")


if __name__ == "__main__":
    test_proc_01_parent_exits_while_descendants_live()
    test_proc_02_nested_runtime_breakaway_attempt()
    test_proc_03_stdin_write_and_close_failure()
    test_proc_04_job_object_lifecycle_and_diagnostics()
    print("ALL P0 Process Containment tests PASS (PROC-01..PROC-04)")
