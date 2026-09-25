#!/usr/bin/env python3
"""Run one harness-neutral qualification task and emit one immutable-style receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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


def observed_resources() -> dict[str, object]:
    """Capture cheap execution-resource facts without turning every rep into a profiler."""
    cpu_model = None
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                cpu_model = line.split(":", 1)[1].strip()
                break
    elif platform.system() == "Darwin":
        for key in ("machdep.cpu.brand_string", "hw.model"):
            probe = subprocess.run(
                ["sysctl", "-n", key],
                text=True,
                capture_output=True,
                check=False,
            )
            value = probe.stdout.strip()
            if probe.returncode == 0 and value:
                cpu_model = value
                break

    memory_total_bytes = None
    try:
        memory_total_bytes = int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        pass

    cpu_quota_cores = None
    cpu_max = Path("/sys/fs/cgroup/cpu.max")
    if cpu_max.exists():
        parts = cpu_max.read_text(encoding="utf-8", errors="replace").strip().split()
        if len(parts) == 2 and parts[0] != "max":
            try:
                quota, period = int(parts[0]), int(parts[1])
                if quota > 0 and period > 0:
                    cpu_quota_cores = round(quota / period, 6)
            except ValueError:
                pass

    cpuset = None
    cpuset_path = Path("/sys/fs/cgroup/cpuset.cpus.effective")
    if cpuset_path.exists():
        cpuset = cpuset_path.read_text(encoding="utf-8", errors="replace").strip() or None

    return {
        "logical_cpus_visible": os.cpu_count(),
        "cpu_model": cpu_model,
        "memory_total_bytes": memory_total_bytes,
        "cpu_quota_cores": cpu_quota_cores,
        "cpuset_cpus_effective": cpuset,
        "platform_system": platform.system() or None,
        "platform_machine": platform.machine() or None,
    }


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


def _signal_candidate_group_or_process(
    proc: subprocess.Popen[str], sig: signal.Signals
) -> bool:
    """Best-effort signal without letting cleanup errors erase run evidence.

    POSIX process-group signaling is preferred because candidates may spawn
    descendants. Some hosted macOS process groups can reject killpg even though
    the runner still owns and can signal the candidate process itself. Fall back
    to the direct process signal so timeout evidence can still be captured.
    """
    if os.name == "posix":
        try:
            os.killpg(proc.pid, sig)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
    if proc.poll() is not None:
        return False
    try:
        proc.send_signal(sig)
        return True
    except ProcessLookupError:
        return False


def _terminate_candidate_group(proc: subprocess.Popen[str]) -> None:
    # Always attempt process-group cleanup even when the group leader has already
    # exited: descendants may still be alive in that session/process group.
    _signal_candidate_group_or_process(proc, signal.SIGTERM)
    time.sleep(0.05)
    _signal_candidate_group_or_process(proc, signal.SIGKILL)


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


def run_science_projector(
    stdout: str,
    *,
    projector: Path,
    output: Path,
    source_ref: str,
    forbidden_root: Path | None = None,
    timeout_seconds: int = 30,
) -> dict[str, object]:
    """Run an explicitly selected privacy projector over ephemeral stdout.

    This hook is telemetry-only. It returns projection/O&M status and never
    changes the candidate or verifier result. The raw temporary source is
    deleted in a finally block and is never returned in the status record.
    """
    status: dict[str, object] = {
        "configured": True,
        "success": False,
        "projector_returncode": None,
        "projector_timed_out": False,
        "output_present": False,
        "source_deleted": False,
    }

    projector = projector.resolve()
    output = output.resolve()

    if forbidden_root is not None:
        root = forbidden_root.resolve()
        try:
            projector.relative_to(root)
        except ValueError:
            pass
        else:
            status["failure_class"] = "projector-inside-candidate-workspace"
            status["source_deleted"] = True
            return status

        try:
            output.relative_to(root)
        except ValueError:
            pass
        else:
            status["failure_class"] = "output-inside-candidate-workspace"
            status["source_deleted"] = True
            return status

    if not projector.is_file():
        status["failure_class"] = "projector-not-found"
        status["source_deleted"] = True
        return status

    if output.exists():
        status["failure_class"] = "projection-output-exists"
        status["output_present"] = True
        status["source_deleted"] = True
        return status

    output.parent.mkdir(parents=True, exist_ok=True)

    source_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="model-spelunker-science-source-",
            suffix=".log",
            delete=False,
        ) as source_file:
            source_file.write(stdout)
            source_path = Path(source_file.name)

        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(projector),
                    str(source_path),
                    "--source-ref",
                    source_ref,
                    "--output",
                    str(output),
                ],
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            status["projector_timed_out"] = True
            status["failure_class"] = "projector-timeout"
        else:
            status["projector_returncode"] = completed.returncode
            status["output_present"] = output.is_file()
            status["success"] = completed.returncode == 0 and output.is_file()
            if not status["success"]:
                status["failure_class"] = (
                    "projector-nonzero"
                    if completed.returncode != 0
                    else "projection-output-missing"
                )
    finally:
        if source_path is not None:
            source_path.unlink(missing_ok=True)
            status["source_deleted"] = not source_path.exists()

    return status

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


def model_call_start_summary(stdout: str) -> dict[str, object]:
    starts: list[dict[str, object]] = []
    prefix = "MODEL_SPELUNKER_MODEL_CALL_STARTED="
    for line in stdout.splitlines():
        if not line.startswith(prefix):
            continue
        try:
            value = json.loads(line[len(prefix):])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            starts.append(value)
    summary: dict[str, object] = {"model_calls_started": len(starts)}
    for source, target in (
        ("request_message_bytes", "started_request_message_bytes_total"),
        ("request_tool_schema_bytes", "started_request_tool_schema_bytes_total"),
    ):
        values = [x.get(source) for x in starts if isinstance(x.get(source), (int, float))]
        if values:
            summary[target] = float(sum(values))
    return summary


def incremental_provider_observations(stdout: str) -> list[dict[str, object]]:
    """Recover completed model-call observations emitted before an interrupted exit."""
    rows: list[dict[str, object]] = []
    prefix = "MODEL_SPELUNKER_MODEL_CALL_COMPLETED="
    for line in stdout.splitlines():
        if not line.startswith(prefix):
            continue
        try:
            value = json.loads(line[len(prefix):])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        row = dict(value)
        row.pop("index", None)
        rows.append(row)
    return rows


def openworker_progress_summary(stdout: str) -> dict[str, object]:
    """Reduce flush-on-event OpenWorker progress that survives timeout termination."""
    started = 0
    finished = 0
    finished_names: list[str] = []
    finished_statuses: list[str] = []
    prefix = "OPENWORKER_EVENT="
    for line in stdout.splitlines():
        if not line.startswith(prefix):
            continue
        try:
            value = json.loads(line[len(prefix):])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        event_type = value.get("type")
        if event_type == "EventType.TOOL_STARTED":
            started += 1
        elif event_type == "EventType.TOOL_FINISHED":
            finished += 1
            name = value.get("name")
            status = value.get("status")
            if isinstance(name, str) and name:
                finished_names.append(name)
            if isinstance(status, str) and status:
                finished_statuses.append(status)
    summary: dict[str, object] = {
        "tool_calls_started": started,
        "tool_calls_completed": finished,
    }
    if finished_names:
        summary["completed_tool_names"] = finished_names
    if finished_statuses:
        summary["completed_tool_statuses"] = finished_statuses
    return summary


def openworker_turn_end_status(stdout: str) -> str | None:
    """Return the final OpenWorker TURN_END status, when emitted."""
    status: str | None = None
    prefix = "OPENWORKER_EVENT="
    for line in stdout.splitlines():
        if not line.startswith(prefix):
            continue
        try:
            value = json.loads(line[len(prefix):])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or value.get("type") != "EventType.TURN_END":
            continue
        observed = value.get("status")
        if isinstance(observed, str) and observed:
            status = observed
    return status


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
    summary: dict[str, object] = {
        "model_rounds": len(observations),
        "model_calls_completed": len(observations),
    }
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


def validate_task_workspace_layout(task_dir: Path, task: dict[str, object]) -> None:
    """Reject package-only fixture paths before a candidate can consume quota."""
    fixture = task.get("fixture")
    if not isinstance(fixture, str) or not fixture or "/" in fixture or "\\" in fixture:
        raise ValueError("task.fixture must be one package-local directory name")
    if not (task_dir / fixture).is_dir():
        raise ValueError(f"task fixture directory not found: {fixture}")

    instruction = task.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("task.instruction must be a non-empty string")
    forbidden = fixture.rstrip("/") + "/"
    if forbidden in instruction:
        raise ValueError(
            f"task instruction addresses non-existent workspace path {forbidden!r}; "
            "fixture contents are materialized at workspace root"
        )

    allowed = task.get("allowed_write_paths") or []
    if not isinstance(allowed, list) or not all(isinstance(x, str) and x for x in allowed):
        raise ValueError("task.allowed_write_paths must be a list of non-empty strings")
    if any(x == fixture or x.startswith(forbidden) for x in allowed):
        raise ValueError("task allowed_write_paths may not target the package fixture directory")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_dir", type=Path)
    parser.add_argument("candidate_metadata", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--task-commit", required=True)
    parser.add_argument("--substrate-profile-id", required=True)
    parser.add_argument("--substrate-profile-commit", required=True)
    parser.add_argument(
        "--substrate-profile-digest",
        help="Optional canonical digest of the external substrate profile bound by the launch packet.",
    )
    parser.add_argument("--launch-id")
    parser.add_argument("--launch-packet-digest")
    parser.add_argument(
        "--diagnostics",
        type=Path,
        help="Optional bounded raw diagnostics file. Use only on credential-free qualification reps.",
    )
    parser.add_argument(
        "--experiment",
        type=Path,
        help="Optional v2 scientific experiment declaration bound into the immutable receipt.",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        help="Optional evidence directory for copies of only task-declared allowed outputs.",
    )
    parser.add_argument(
        "--candidate-env-mode",
        choices=["inherit", "minimal"],
        default="inherit",
        help="Environment policy for the candidate process. Portable/local launches should prefer minimal.",
    )
    parser.add_argument(
        "--pass-env",
        action="append",
        default=[],
        help="Environment variable name to pass explicitly in minimal mode; may be repeated.",
    )
    parser.add_argument(
        "--science-projector",
        type=Path,
        help=(
            "Optional trusted Python projector. Receives an ephemeral candidate "
            "stdout file plus --source-ref and --output arguments."
        ),
    )
    parser.add_argument(
        "--science-projection-output",
        type=Path,
        help="Durable output path for the optional privacy-safe science projection.",
    )
    parser.add_argument(
        "--wall-seconds",
        type=int,
        help="Optional prospective wall-clock treatment override; default is task limits.wall_seconds.",
    )
    parser.add_argument(
        "--projected-tools-source",
        choices=["task", "candidate"],
        default="task",
        help=(
            "Select the effective tool projection from the task profile (default) or the "
            "configured actor toolset. Candidate mode is for prospective tool-surface "
            "factor experiments; it does not alter write-path validation."
        ),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("candidate command is required after --")

    if bool(args.launch_id) != bool(args.launch_packet_digest):
        parser.error("--launch-id and --launch-packet-digest must be supplied together")

    task = json.loads((args.task_dir / "task.json").read_text(encoding="utf-8"))
    validate_task_workspace_layout(args.task_dir, task)
    candidate = json.loads(args.candidate_metadata.read_text(encoding="utf-8"))
    experiment_meta = None
    if args.experiment is not None:
        experiment_doc = json.loads(args.experiment.read_text(encoding="utf-8"))
        if experiment_doc.get("schema_version") != 2:
            raise ValueError("scientific experiment declaration must use schema_version 2")
        if (experiment_doc.get("task") or {}).get("id") != task["id"]:
            raise ValueError("experiment task id does not match executed task")
        experiment_meta = {
            "id": experiment_doc["id"],
            "digest": canonical_json_digest(experiment_doc),
            "claim_type": experiment_doc["claim_type"],
            "experimental_role": experiment_doc["experimental_role"],
            "design_block": experiment_doc.get("design_block"),
            "primary_responses": experiment_doc["primary_responses"],
        }
    task_wall_seconds = int(task["limits"]["wall_seconds"])
    timeout = int(args.wall_seconds) if args.wall_seconds is not None else task_wall_seconds
    if timeout < 1:
        parser.error("--wall-seconds must be >= 1")

    run_id = new_run_id()

    with tempfile.TemporaryDirectory(prefix="model-spelunker-qual-") as temp:
        workdir = Path(temp) / "work"
        shutil.copytree(args.task_dir / task["fixture"], workdir)
        initial_tree_digest = tree_digest(workdir)

        started = time.monotonic()
        if args.candidate_env_mode == "inherit":
            candidate_env = dict(os.environ)
        else:
            baseline = {
                "PATH",
                "HOME",
                "LANG",
                "LC_ALL",
                "TMPDIR",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
            }
            requested = baseline | set(args.pass_env)
            candidate_env = {
                key: value
                for key, value in os.environ.items()
                if key in requested
            }
        candidate_env["MODEL_SPELUNKER_TASK_ID"] = task["id"]
        allowed = task.get("allowed_write_paths") or []
        if len(allowed) == 1:
            candidate_env["MODEL_SPELUNKER_WRITE_TARGET"] = str(allowed[0])
        if args.projected_tools_source == "candidate":
            projected_tools = candidate.get("toolset") or []
            if not isinstance(projected_tools, list) or not all(
                isinstance(x, str) and x for x in projected_tools
            ):
                raise ValueError("candidate toolset must be a list of non-empty strings")
        else:
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
        if candidate_env.get("MODEL_SPELUNKER_PUBLIC_DIAGNOSTICS") == "1":
            print(
                "MODEL_SPELUNKER_PUBLIC_STDOUT_TAIL="
                + json.dumps(stdout[-4096:]),
                flush=True,
            )
            print(
                "MODEL_SPELUNKER_PUBLIC_STDERR_TAIL="
                + json.dumps(stderr[-4096:]),
                flush=True,
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
        if not provider_rounds:
            provider_rounds = incremental_provider_observations(stdout)
        if not provider_rounds and (candidate.get("harness") or {}).get("name") == "goose":
            provider_rounds = goose_stream_provider_observations(stdout)
        engine_error = has_engine_error_event(stdout)
        turn_end_status = openworker_turn_end_status(stdout)
        iteration_censored = turn_end_status == "max_iterations_exceeded"
        if success:
            failure_class = None
        elif validator_error:
            failure_class = "validator-error"
        elif timed_out:
            failure_class = "timeout"
        elif candidate_exit != 0:
            failure_class = "candidate-error"
        elif verifier.returncode != 0 and engine_error:
            failure_class = "candidate-error-event"
        elif iteration_censored:
            failure_class = "iteration-limit"
        elif verifier.returncode != 0:
            failure_class = "false-completion"
        else:
            failure_class = None

        if success:
            termination_class = "semantic-success"
        elif validator_error:
            termination_class = "validator-invalid"
        elif timed_out:
            termination_class = "timeout-censored"
        elif candidate_exit != 0 or engine_error:
            termination_class = "execution-error"
        elif iteration_censored:
            termination_class = "iteration-censored"
        else:
            termination_class = "semantic-failure"

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
        if (
            not success
            and iteration_censored
            and "iteration-limit" not in failure_signals
        ):
            failure_signals.append("iteration-limit")
        metrics = harness_metrics(stdout)
        progress = openworker_progress_summary(stdout)
        if metrics["tool_calls"] is None and int(progress.get("tool_calls_completed", 0)) > 0:
            metrics["tool_calls"] = int(progress["tool_calls_completed"])
        mobile_actions: list[dict[str, object]] = []
        mobile_raw = last_marker(stdout, "MODEL_SPELUNKER_MOBILE_ACTIONS=")
        if mobile_raw:
            try:
                mobile_parsed = json.loads(mobile_raw)
            except json.JSONDecodeError:
                mobile_parsed = []
            if isinstance(mobile_parsed, list):
                mobile_actions = [
                    item for item in mobile_parsed if isinstance(item, dict)
                ]
        error_types = engine_error_types(stdout)
        workload = workload_summary(provider_rounds)
        workload.update(model_call_start_summary(stdout))
        workload.update(progress)

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
            "schema_version": 2 if experiment_meta is not None else 1,
            "run_id": run_id,
            "task": {
                "id": task["id"],
                "task_class": task.get("task_class"),
                "source_commit": args.task_commit,
                "package_digest": tree_digest(args.task_dir),
                **(
                    {"ksa_requirements": task["ksa_requirements"]}
                    if task.get("ksa_requirements")
                    else {}
                ),
            },
            "candidate": {
                "harness": candidate["harness"],
                "model": candidate["model"],
                "configuration_digest": canonical_json_digest(candidate),
                "toolset": candidate["toolset"],
                **(
                    {"configuration": candidate["configuration"]}
                    if experiment_meta is not None and "configuration" in candidate
                    else {}
                ),
                **({"build": candidate["build"]} if "build" in candidate else {}),
                **(
                    {"deployment_topology": candidate["deployment_topology"]}
                    if "deployment_topology" in candidate
                    else {}
                ),
            },
            "substrate": {
                "profile_id": args.substrate_profile_id,
                "profile_commit": args.substrate_profile_commit,
                **(
                    {"profile_digest": args.substrate_profile_digest}
                    if args.substrate_profile_digest
                    else {}
                ),
            },
            "resources": observed_resources(),
            "execution_limits": {
                "wall_seconds": timeout,
                "wall_seconds_source": "override" if args.wall_seconds is not None else "task",
            },
            **({"experiment": experiment_meta} if experiment_meta is not None else {}),
            **(
                {
                    "launch": {
                        "launch_id": args.launch_id,
                        "packet_digest": args.launch_packet_digest,
                    }
                }
                if args.launch_id and args.launch_packet_digest
                else {}
            ),
            "observation": {
                "success": success,
                "termination_class": termination_class,
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
                "mobile_action_count": len(mobile_actions),
                "mobile_actions": mobile_actions,
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

        if args.science_projector is not None:
            projection_status = run_science_projector(
                stdout,
                projector=args.science_projector,
                output=args.science_projection_output,
                source_ref=f"ephemeral:qualification-run/{run_id}/candidate-stdout",
                forbidden_root=workdir,
            )
            print(
                "MODEL_SPELUNKER_SCIENCE_PROJECTION="
                + json.dumps(projection_status, sort_keys=True),
                flush=True,
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
