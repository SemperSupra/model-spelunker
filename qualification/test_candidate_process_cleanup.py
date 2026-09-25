#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from qualification import run_task


original_killpg = run_task.os.killpg


def denied_killpg(_pid, _sig):
    raise PermissionError(1, "operation not permitted")


try:
    run_task.os.killpg = denied_killpg
    rc, stdout, stderr, timed_out = run_task.run_candidate_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=Path.cwd(),
        input_text="",
        timeout=1,
        env=dict(os.environ),
    )
finally:
    run_task.os.killpg = original_killpg

assert timed_out is True
assert rc == 124
assert stdout == ""
assert stderr == ""
print("PASS candidate timeout survives POSIX killpg permission denial")
