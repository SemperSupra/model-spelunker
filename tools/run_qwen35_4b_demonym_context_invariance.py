#!/usr/bin/env python3
"""Experiment 0002 R19: held-out demonym-context replication.

Reuse the proven R18 context-invariance apparatus unchanged except for the
held-out downstream context. After the R18 harness writes its artifacts, relabel
the summary as R19 so provenance remains explicit without forking the causal
implementation.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_FIXTURE = (
    "fixtures/experiment-0002/"
    "multilingual-indirect-bridge-demonym-context-holdout.jsonl"
)
DEFAULT_OUTPUT = "artifacts/experiment-0002-qwen35-4b-demonym-context-invariance"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", default=DEFAULT_FIXTURE)
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cmd = [
        sys.executable,
        "tools/run_qwen35_4b_context_invariance.py",
        "--fixture",
        args.fixture,
        "--output-dir",
        args.output_dir,
    ]
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        return completed.returncode

    summary_path = Path(args.output_dir) / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["experiment"] = "0002-r19-qwen35-4b-demonym-context-invariance"
    summary["purpose"] = (
        "held-out demonym prompt-context replication with the frozen R16-R18 "
        "country addresses, layers, strength, and empirical-null seeds"
    )
    summary["parent_harness"] = "tools/run_qwen35_4b_context_invariance.py"
    summary["r18_context_invariance_pass_prerequisite"] = True
    summary["next_if_pass"] = (
        "promote the validated country addresses to composition and Experiment "
        "0003 trajectory tests; do not widen intervention tuning"
    )
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
