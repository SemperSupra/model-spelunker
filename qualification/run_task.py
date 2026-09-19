#!/usr/bin/env python3
"""Run one harness-neutral qualification task and emit one immutable-style receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_json_digest(value: object) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def tree_digest(root: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        hasher.update(relative)
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return "sha256:" + hasher.hexdigest()


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_dir", type=Path)
    parser.add_argument("candidate_metadata", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--task-commit", required=True)
    parser.add_argument("--substrate-profile-id", required=True)
    parser.add_argument("--substrate-profile-commit", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("candidate command is required after --")

    task = json.loads((args.task_dir / "task.json").read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate_metadata.read_text(encoding="utf-8"))
    timeout = int(task["limits"]["wall_seconds"])

    with tempfile.TemporaryDirectory(prefix="model-spelunker-qual-") as temp:
        workdir = Path(temp) / "work"
        shutil.copytree(args.task_dir / task["fixture"], workdir)

        started = time.monotonic()
        try:
            candidate_env = dict(os.environ)
            candidate_env["MODEL_SPELUNKER_TASK_ID"] = task["id"]
            completed = subprocess.run(
                command,
                cwd=workdir,
                text=True,
                input=task["instruction"] + "\n",
                capture_output=True,
                timeout=timeout,
                check=False,
                env=candidate_env,
            )
            candidate_exit = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            candidate_exit = 124
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            timed_out = True

        verifier = subprocess.run(
            [sys.executable, str(args.task_dir / task["verifier"]), str(workdir)],
            text=True,
            capture_output=True,
            check=False,
        )
        wall_seconds = time.monotonic() - started

        success = verifier.returncode == 0 and not timed_out
        if timed_out:
            failure_class = "timeout"
        elif verifier.returncode != 0:
            failure_class = "verifier-failure"
        else:
            failure_class = None

        evidence = {
            "candidate_exit_code": candidate_exit,
            "candidate_stdout_sha256": sha256_bytes(stdout.encode("utf-8")),
            "candidate_stderr_sha256": sha256_bytes(stderr.encode("utf-8")),
            "verifier_exit_code": verifier.returncode,
            "verifier_stdout_sha256": sha256_bytes(verifier.stdout.encode("utf-8")),
            "verifier_stderr_sha256": sha256_bytes(verifier.stderr.encode("utf-8")),
            "final_tree_digest": tree_digest(workdir),
        }

        receipt = {
            "schema_version": 1,
            "run_id": new_run_id(),
            "task": {
                "id": task["id"],
                "source_commit": args.task_commit,
            },
            "candidate": {
                "harness": candidate["harness"],
                "model": candidate["model"],
                "configuration_digest": canonical_json_digest(candidate),
                "toolset": candidate["toolset"],
            },
            "substrate": {
                "profile_id": args.substrate_profile_id,
                "profile_commit": args.substrate_profile_commit,
            },
            "observation": {
                "success": success,
                "failure_class": failure_class,
                "wall_seconds": round(wall_seconds, 6),
                "human_interventions": 0,
                "candidate_exit_code": candidate_exit,
                "verifier_exit_code": verifier.returncode,
                "tool_calls": None,
                "input_tokens": None,
                "output_tokens": None,
                "cost": None,
            },
            "evidence_digest": canonical_json_digest(evidence),
        }

        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(receipt, sort_keys=True))
        return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
