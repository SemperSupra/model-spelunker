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


def detect_failure_signals(
    stdout: str,
    stderr: str,
    *,
    timed_out: bool,
    candidate_exit: int,
    verifier_exit: int,
    state_changed: bool,
) -> list[str]:
    """Return bounded, evidence-backed failure signals without replacing the terminal class."""

    combined = f"{stdout}\n{stderr}"
    signals: list[str] = []

    def add(signal: str) -> None:
        if signal not in signals:
            signals.append(signal)

    if timed_out:
        add("timeout")
    if candidate_exit == 0 and verifier_exit != 0:
        add("false-completion")
    if verifier_exit != 0 and not state_changed:
        add("state-unchanged")

    signatures = {
        "invalid-tool-call": (
            "write_stdin failed: Unknown process id",
            "invalid tool call",
            "invalid_tool_call",
        ),
        "authority-mismatch": (
            "approval policy is Never; reject command",
            "cannot ask for escalated permissions",
        ),
        "sandbox-helper-unavailable": (
            "Unable to spawn codex-linux-sandbox",
            "No viable candidates found in PATH",
            "missing codex-linux-sandbox executable path",
        ),
        "sandbox-user-namespace-unavailable": (
            "loopback: Failed RTM_NEWADDR",
            "loopback: Failed RTM_NEWLINK",
            "setting up uid map: Permission denied",
            "No permissions to create a new namespace",
        ),
        "sandbox-policy-incompatible": (
            "permission profiles requiring direct runtime enforcement are incompatible with --use-legacy-landlock",
        ),
        "unexpected-external-network": (
            "failed to warm featured plugin ids cache error=remote featured plugin request",
        ),
    }

    tool_failure_hits = 0
    for signal, needles in signatures.items():
        hits = sum(combined.count(needle) for needle in needles)
        if hits:
            add(signal)
        if signal in {
            "invalid-tool-call",
            "authority-mismatch",
            "sandbox-helper-unavailable",
            "sandbox-user-namespace-unavailable",
            "sandbox-policy-incompatible",
        }:
            tool_failure_hits += hits

    if tool_failure_hits >= 2:
        add("repeated-tool-failure")

    return signals


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def last_marker(stdout: str, prefix: str) -> str | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            return line[len(prefix):]
    return None


def harness_metrics(stdout: str) -> dict[str, int | None]:
    usage_raw = last_marker(stdout, "MODEL_SPELUNKER_USAGE=")
    usage: dict[str, int] = {}
    if usage_raw:
        try:
            parsed = json.loads(usage_raw)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            for key in ("input", "output", "cache_read", "cache_write"):
                value = parsed.get(key)
                if isinstance(value, int) and value >= 0:
                    usage[key] = value

    tool_calls: int | None = None
    tool_raw = last_marker(stdout, "MODEL_SPELUNKER_TOOL_CALLS=")
    if tool_raw is not None:
        try:
            value = int(tool_raw)
        except ValueError:
            pass
        else:
            if value >= 0:
                tool_calls = value

    return {
        "tool_calls": tool_calls,
        "input_tokens": usage.get("input"),
        "output_tokens": usage.get("output"),
        "cache_read_tokens": usage.get("cache_read"),
        "cache_write_tokens": usage.get("cache_write"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_dir", type=Path)
    parser.add_argument("candidate_metadata", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--task-commit", required=True)
    parser.add_argument("--substrate-profile-id", required=True)
    parser.add_argument("--substrate-profile-commit", required=True)
    parser.add_argument(
        "--diagnostics",
        type=Path,
        help="Optional bounded raw diagnostics file. Use only on credential-free qualification reps.",
    )
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
        initial_tree_digest = tree_digest(workdir)

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
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            timed_out = True

        verifier = subprocess.run(
            [sys.executable, str(args.task_dir / task["verifier"]), str(workdir)],
            text=True,
            capture_output=True,
            check=False,
        )
        wall_seconds = time.monotonic() - started

        final_tree_digest = tree_digest(workdir)
        state_changed = final_tree_digest != initial_tree_digest
        success = verifier.returncode == 0 and not timed_out
        if timed_out:
            failure_class = "timeout"
        elif candidate_exit != 0:
            failure_class = "candidate-error"
        elif verifier.returncode != 0:
            failure_class = "false-completion"
        else:
            failure_class = None

        failure_signals = detect_failure_signals(
            stdout,
            stderr,
            timed_out=timed_out,
            candidate_exit=candidate_exit,
            verifier_exit=verifier.returncode,
            state_changed=state_changed,
        )
        metrics = harness_metrics(stdout)

        evidence = {
            "candidate_exit_code": candidate_exit,
            "candidate_stdout_sha256": sha256_bytes(stdout.encode("utf-8")),
            "candidate_stderr_sha256": sha256_bytes(stderr.encode("utf-8")),
            "verifier_exit_code": verifier.returncode,
            "verifier_stdout_sha256": sha256_bytes(verifier.stdout.encode("utf-8")),
            "verifier_stderr_sha256": sha256_bytes(verifier.stderr.encode("utf-8")),
            "initial_tree_digest": initial_tree_digest,
            "final_tree_digest": final_tree_digest,
        }

        diagnostics = {
            "candidate_stdout_chars": len(stdout),
            "candidate_stderr_chars": len(stderr),
            "candidate_stdout_tail": stdout[-8192:],
            "candidate_stderr_tail": stderr[-8192:],
            "verifier_stdout_tail": verifier.stdout[-4096:],
            "verifier_stderr_tail": verifier.stderr[-4096:],
        }

        receipt = {
            "schema_version": 1,
            "run_id": new_run_id(),
            "task": {
                "id": task["id"],
                "source_commit": args.task_commit,
                "package_digest": tree_digest(args.task_dir),
            },
            "candidate": {
                "harness": candidate["harness"],
                "model": candidate["model"],
                "configuration_digest": canonical_json_digest(candidate),
                "toolset": candidate["toolset"],
                **({"build": candidate["build"]} if "build" in candidate else {}),
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
                "timed_out": timed_out,
                "state_changed": state_changed,
                "failure_signals": failure_signals,
                "tool_calls": metrics["tool_calls"],
                "input_tokens": metrics["input_tokens"],
                "output_tokens": metrics["output_tokens"],
                "cache_read_tokens": metrics["cache_read_tokens"],
                "cache_write_tokens": metrics["cache_write_tokens"],
                "cost": None,
            },
            "evidence_digest": canonical_json_digest(evidence),
        }

        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if args.diagnostics is not None:
            args.diagnostics.parent.mkdir(parents=True, exist_ok=True)
            args.diagnostics.write_text(
                json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(receipt, sort_keys=True))
        return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
