#!/usr/bin/env python3
"""Run one harness-neutral qualification task and emit one immutable-style receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
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


def snapshot_allowed_outputs(
    workdir: Path, allowed_paths: list[str], snapshot_dir: Path
) -> dict[str, object]:
    """Copy only declared task outputs out of the disposable workspace.

    The snapshot is evidence, not acceptance. Missing outputs are recorded rather
    than synthesized, and source/fixture files are never copied implicitly.
    """
    root = workdir.resolve()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, object] = {}
    for relative in allowed_paths:
        source = (workdir / relative).resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"allowed output escapes workspace: {relative}") from exc
        if not source.is_file():
            files[relative] = {"present": False}
            continue
        data = source.read_bytes()
        target = snapshot_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files[relative] = {
            "present": True,
            "sha256": sha256_bytes(data),
            "size_bytes": len(data),
        }
    manifest = {"schema_version": 1, "files": files}
    (snapshot_dir / "snapshot_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def engine_error_types(stdout: str) -> list[str]:
    out: list[str] = []
    for line in stdout.splitlines():
        if not line.startswith("OPENWORKER_EVENT="):
            continue
        try:
            event = json.loads(line.split("=", 1)[1])
        except (json.JSONDecodeError, IndexError):
            continue
        if event.get("type") != "EventType.ERROR":
            continue
        value = event.get("error_type")
        normalized = str(value).strip() if value is not None else "unspecified"
        if normalized and normalized not in out:
            out.append(normalized)
    return out


def has_engine_error_event(stdout: str) -> bool:
    return bool(engine_error_types(stdout))


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

    engine_error = has_engine_error_event(stdout)
    if timed_out:
        add("timeout")
    if engine_error:
        add("engine-error-event")
    if candidate_exit == 0 and verifier_exit != 0 and not engine_error:
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


def _terminate_candidate_group(proc: subprocess.Popen[str]) -> None:
    if os.name != "posix":
        if proc.poll() is None:
            proc.terminate()
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(0.05)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_candidate_process(
    command: list[str],
    *,
    cwd: Path,
    input_text: str,
    timeout: int,
    env: dict[str, str],
) -> tuple[int, str, str, bool]:
    """Run a candidate in its own process group and never leave descendants behind.

    Regular temp files are used for stdout/stderr so a background descendant that
    inherits those descriptors cannot keep the parent-side capture pipe open after
    the candidate process itself exits.
    """
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+", encoding="utf-8"
    ) as stderr_file:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            text=True,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            env=env,
            start_new_session=(os.name == "posix"),
        )
        if proc.stdin is None:
            raise RuntimeError("candidate stdin unavailable")
        proc.stdin.write(input_text)
        proc.stdin.close()

        timed_out=False
        try:
            return_code=proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
            return_code=124
        finally:
            _terminate_candidate_group(proc)
            if proc.poll() is None:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout=stdout_file.read()
        stderr=stderr_file.read()
        return return_code, stdout, stderr, timed_out

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


def provider_observations(stdout: str) -> list[dict[str, object]]:
    raw = last_marker(stdout, "MODEL_SPELUNKER_PROVIDER_OBSERVATIONS=")
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def goose_stream_provider_observations(stdout: str) -> list[dict[str, object]]:
    """Project Goose stream-json assistant turns into provider-round observations.

    Goose emits one message event per streamed chunk, with all chunks from one
    assistant turn sharing message.id. This mirrors Goose's own Harbor reporter:
    dedupe assistant message events by id so streamed tokens do not inflate the
    model-round count. Only explicitly observed inference metadata is retained.
    """
    turns: dict[str, dict[str, object]] = {}
    anonymous: list[dict[str, object]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "message":
            continue
        message = obj.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        metadata = message.get("metadata")
        inference = metadata.get("inference") if isinstance(metadata, dict) else None
        observation: dict[str, object] = {}
        if isinstance(inference, dict):
            provider = inference.get("provider")
            requested = inference.get("requestedModel")
            if isinstance(provider, str) and provider:
                observation["provider"] = provider
            if isinstance(requested, str) and requested:
                observation["requested_model"] = requested
        message_id = message.get("id")
        if isinstance(message_id, str) and message_id:
            turns.setdefault(message_id, observation)
        else:
            anonymous.append(observation)
    return list(turns.values()) + anonymous


def workload_summary(observations: list[dict[str, object]]) -> dict[str, object]:
    numeric_fields = (
        "request_message_bytes",
        "request_tool_schema_bytes",
        "output_text_bytes",
        "reasoning_bytes",
        "tool_argument_bytes",
        "client_wall_seconds",
    )
    summary: dict[str, object] = {"model_rounds": len(observations)}
    for field in numeric_fields:
        values = [
            item.get(field)
            for item in observations
            if isinstance(item.get(field), (int, float))
        ]
        if values:
            summary[field + "_total"] = round(float(sum(values)), 6)

    ttft = [
        float(item["first_event_seconds"])
        for item in observations
        if isinstance(item.get("first_event_seconds"), (int, float))
    ]
    if ttft:
        summary["first_event_seconds_first"] = round(ttft[0], 6)
        summary["first_event_seconds_min"] = round(min(ttft), 6)
        summary["first_event_seconds_max"] = round(max(ttft), 6)

    resolved_models = sorted(
        {
            str(item["resolved_model"])
            for item in observations
            if isinstance(item.get("resolved_model"), str) and item.get("resolved_model")
        }
    )
    serving_providers: set[str] = set()
    system_fingerprints: set[str] = set()
    service_tiers: set[str] = set()
    provider_reported_cost_total = 0.0
    provider_cost_seen = False
    is_byok_values: set[bool] = set()
    provider_metadata_errors: set[str] = set()
    native_totals = {
        "native_prompt_tokens_total": 0,
        "native_completion_tokens_total": 0,
        "native_reasoning_tokens_total": 0,
        "native_cached_tokens_total": 0,
    }
    native_seen = {key: False for key in native_totals}

    for item in observations:
        direct = item.get("provider")
        if isinstance(direct, str) and direct:
            serving_providers.add(direct)
        fingerprint = item.get("system_fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            system_fingerprints.add(fingerprint)
        tier = item.get("service_tier")
        if isinstance(tier, str) and tier:
            service_tiers.add(tier)

        metadata_error = item.get("openrouter_generation_error")
        if isinstance(metadata_error, str) and metadata_error:
            provider_metadata_errors.add(metadata_error)

        generation = item.get("openrouter_generation")
        if isinstance(generation, dict):
            provider = generation.get("provider_name")
            if isinstance(provider, str) and provider:
                serving_providers.add(provider)
            model = generation.get("model")
            if isinstance(model, str) and model:
                resolved_models.append(model)
            generation_tier = generation.get("service_tier")
            if isinstance(generation_tier, str) and generation_tier:
                service_tiers.add(generation_tier)
            is_byok = generation.get("is_byok")
            if isinstance(is_byok, bool):
                is_byok_values.add(is_byok)

            cost = generation.get("total_cost")
            if isinstance(cost, (int, float)) and cost >= 0:
                provider_reported_cost_total += float(cost)
                provider_cost_seen = True

            native_map = {
                "native_prompt_tokens_total": "native_tokens_prompt",
                "native_completion_tokens_total": "native_tokens_completion",
                "native_reasoning_tokens_total": "native_tokens_reasoning",
                "native_cached_tokens_total": "native_tokens_cached",
            }
            for target, source in native_map.items():
                value = generation.get(source)
                if isinstance(value, int) and value >= 0:
                    native_totals[target] += value
                    native_seen[target] = True
        else:
            cost = item.get("provider_cost")
            if isinstance(cost, (int, float)) and cost >= 0:
                provider_reported_cost_total += float(cost)
                provider_cost_seen = True

    if resolved_models:
        summary["resolved_models"] = sorted(set(resolved_models))
    if serving_providers:
        summary["serving_providers"] = sorted(serving_providers)
    if system_fingerprints:
        summary["system_fingerprints"] = sorted(system_fingerprints)
    if service_tiers:
        summary["service_tiers"] = sorted(service_tiers)
    if is_byok_values:
        summary["is_byok_values"] = sorted(is_byok_values)
    if provider_metadata_errors:
        summary["provider_metadata_errors"] = sorted(provider_metadata_errors)
    if provider_cost_seen:
        summary["provider_reported_cost_total"] = round(provider_reported_cost_total, 12)
    for key, value in native_totals.items():
        if native_seen[key]:
            summary[key] = value
    return summary


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
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        help="Optional evidence directory for copies of only task-declared allowed outputs.",
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
        candidate_env = dict(os.environ)
        candidate_env["MODEL_SPELUNKER_TASK_ID"] = task["id"]
        allowed = task.get("allowed_write_paths") or []
        if len(allowed) == 1:
            candidate_env["MODEL_SPELUNKER_WRITE_TARGET"] = str(allowed[0])
        projected_tools = task.get("projected_tools") or []
        if projected_tools:
            candidate_env["MODEL_SPELUNKER_PROJECTED_TOOLS"] = ",".join(projected_tools)
        candidate_exit, stdout, stderr, timed_out = run_candidate_process(
            command,
            cwd=workdir,
            input_text=task["instruction"] + "\n",
            timeout=timeout,
            env=candidate_env,
        )

        verifier = subprocess.run(
            [sys.executable, str(args.task_dir / task["verifier"]), str(workdir)],
            text=True,
            capture_output=True,
            check=False,
        )
        wall_seconds = time.monotonic() - started

        final_tree_digest = tree_digest(workdir)
        state_changed = final_tree_digest != initial_tree_digest
        validator_error = verifier.returncode not in {0, 1}
        success = verifier.returncode == 0 and not timed_out
        provider_rounds = provider_observations(stdout)
        if not provider_rounds and (candidate.get("harness") or {}).get("name") == "goose":
            provider_rounds = goose_stream_provider_observations(stdout)
        engine_error = has_engine_error_event(stdout)
        if validator_error:
            failure_class = "validator-error"
        elif timed_out:
            failure_class = "timeout"
        elif candidate_exit != 0:
            failure_class = "candidate-error"
        elif verifier.returncode != 0 and engine_error:
            failure_class = "candidate-error-event"
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
        if validator_error and "validator-error" not in failure_signals:
            failure_signals.append("validator-error")
        metrics = harness_metrics(stdout)
        error_types = engine_error_types(stdout)
        workload = workload_summary(provider_rounds)

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
                "task_class": task.get("task_class"),
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
                "engine_error_types": error_types,
                "tool_calls": metrics["tool_calls"],
                "input_tokens": metrics["input_tokens"],
                "output_tokens": metrics["output_tokens"],
                "cache_read_tokens": metrics["cache_read_tokens"],
                "cache_write_tokens": metrics["cache_write_tokens"],
                "workload": workload,
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
        if args.snapshot_dir is not None:
            snapshot = snapshot_allowed_outputs(
                workdir,
                list(task.get("allowed_write_paths") or []),
                args.snapshot_dir,
            )
            print("MODEL_SPELUNKER_OUTPUT_SNAPSHOT=" + json.dumps(snapshot, sort_keys=True))
        print(json.dumps(receipt, sort_keys=True))
        return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
