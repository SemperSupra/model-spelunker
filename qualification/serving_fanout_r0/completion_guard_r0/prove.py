#!/usr/bin/env python3
"""Paired resident OpenWorker completion-guard experiment using the canonical runner.

Only public synthetic task packages are permitted. There is no recovery factor,
new agent loop, task verifier, scheduler, or deployment in this fixture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from qualification.run_task import canonical_json_digest, tree_digest

TASK_OUTPUTS = {"text-repair-v0": ["value.txt"], "validation-discovery-v0": ["result.json"]}
ARMS = ("none", "required-files-v1")
HARNESS = "ghcr.io/sempersupra/model-spelunker-harness-openworker@sha256:e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83"
HARNESS_REV = "5bc10d928e0b64aae74313349a3b17bd19643ae2"
ADMISSION = "github:SemperSupra/model-spelunker@4f939c4beccb7652b851c4a228d78d804b0e95c7:qualification/harness-artifacts/openworker-5bc10d928e0b-linux-x64.admission-v2.json"
MODEL_MANIFEST = "sha256:8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
MODEL_BLOB = "sha256:3d0b790534fe4b79525fc3692950408dca41171676ed7e21db57af5c65ef6ab6"
LLAMA_REV = "a6ac41c757c066941766164439f6876f2deaab04"
TASK_WALL_TIMEOUT_S = 240
RUNNER_TIMEOUT_S = 300
HEALTH_TIMEOUT_S = 60
TEARDOWN_TIMEOUT_S = 10
SNAPSHOT_VERIFIER_TIMEOUT_S = 15
EXTRA_BODY = {
    "seed": 42, "temperature": 0, "id_slot": 0, "cache_prompt": True,
    "chat_template_kwargs": {"enable_thinking": False},
}
SOURCE_PATHS = (
    "qualification/run_task.py",
    "qualification/adapters/openworker_projected.py",
    "qualification/adapters/completion_guard.py",
    "qualification/serving_fanout_r0/completion_guard_r0/prove.py",
)


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_schema(document, schema_name):
    from jsonschema import Draft7Validator
    schema = json.loads((ROOT / "qualification" / schema_name).read_bytes())
    Draft7Validator(schema).validate(document)


def experiment_metadata(task, mode, rep):
    task_meta = json.loads((ROOT / "qualification/tasks" / task / "task.json").read_bytes())
    return {
        "schema_version": 2, "id": "openworker-completion-guard-r0-" + task,
        "decision_question": "Does one bounded missing-output nudge improve canonical task acceptance within the unchanged four-call budget?",
        "task": {"id": task, "task_class": task_meta["task_class"]},
        "actors": ["openworker-qwen3-1.7b-" + arm for arm in ARMS],
        "replication": {"reps_per_actor": 3, "independent": True, "randomized_order": False},
        "frozen_factors": ["task-package", "oracle", "harness-artifact", "model-blob", "native-server-revision", "server-flags", "four-model-call-budget", "sampling", "tool-projection"],
        "variable_under_test": "completion_check none vs required-files-v1",
        "claim_type": "feasibility",
        "experimental_role": "control" if mode == "none" else "screening",
        "design_block": "rep-" + str(rep),
        "primary_responses": ["accepted", "full_wall", "completion_nudges", "model_calls"],
        "stop_conditions": ["identity drift", "invalid receipt binding", "native teardown failure"],
        "exclusion_conditions": [],
    }


def ordered_tasks(rep):
    tasks = list(TASK_OUTPUTS)
    return tasks if rep % 2 == 0 else tasks[::-1]


def ordered_arms(rep, task):
    # Alternate the paired order by block and task. Across the six pairs each
    # arm starts three times; each task has three exploratory paired blocks.
    index = list(TASK_OUTPUTS).index(task)
    return list(ARMS if (rep + index) % 2 == 0 else ARMS[::-1])


def candidate_metadata(task, mode, task_digest, source_files):
    require(task in TASK_OUTPUTS and mode in ARMS, "task_or_completion_mode")
    metadata = json.loads((ROOT / "qualification/tasks" / task / "task.json").read_bytes())
    require(metadata["allowed_write_paths"] == TASK_OUTPUTS[task], "unchanged_task_outputs")
    return {
        "harness": {"name": "openworker", "version": HARNESS_REV,
                    "artifact_ref": HARNESS, "admission_ref": ADMISSION},
        "model": {"provider": "local-openai", "id": "completion-guard",
                  "artifact_ref": MODEL_BLOB},
        "toolset": metadata["projected_tools"],
        "configuration": {
            "completion_check": mode,
            "required_output_paths": TASK_OUTPUTS[task],
            "task_id": task, "task_package_digest": task_digest,
            "model_source_manifest": MODEL_MANIFEST,
            "source_files": source_files,
            "parallel_tool_calls": False, "max_tokens": 256,
            "reasoning_effort": "none", "max_iterations": 4,
            "tool_hint_mode": "none", "context_length": 8192,
            "task_wall_timeout_s": TASK_WALL_TIMEOUT_S,
            "runner_timeout_s": RUNNER_TIMEOUT_S,
            "native_readiness_timeout_s": HEALTH_TIMEOUT_S,
            "native_teardown_timeout_s": TEARDOWN_TIMEOUT_S,
            "snapshot_verifier_timeout_s": SNAPSHOT_VERIFIER_TIMEOUT_S,
            "extra_body": EXTRA_BODY,
            "server_revision": LLAMA_REV,
            "server_threads": 4, "server_gpu_layers": 0,
            "server_slots": 1, "server_cache_ram": 0,
            "server_no_cache_idle_slots": True,
            "lifecycle": "fresh-process-per-arm-resident-throughout-task",
        },
    }


def last_json_marker(text, prefix):
    for line in reversed(text.splitlines()):
        if line.startswith(prefix):
            value = json.loads(line[len(prefix):])
            require(isinstance(value, dict), "marker_not_object")
            return value
    return None


def project_diagnostics(raw, mode):
    """Retain only known metadata; raw candidate output is not uploaded."""
    text = raw.get("candidate_stdout_tail", "")
    summary = last_json_marker(text, "OPENWORKER_SUMMARY=")
    nudge = last_json_marker(text, "MODEL_SPELUNKER_COMPLETION_GUARD=")
    guard = summary.get("completion_guard") if summary is not None else None
    require(guard is None or isinstance(guard, dict), "guard_summary_not_object")
    guard_keys = ("mode", "required_output_count", "requirements_sha256", "nudges", "missing_at_nudge", "blocked_reason")
    if guard is not None:
        guard = {key: guard[key] for key in guard_keys if key in guard}
    projected = {
        "schema": "completion-guard-synthetic-diagnostics/v1",
        "raw_stdout_tail_available": bool(text),
        "stdout_tail_sha256": digest(text.encode()),
        "guard_observation": guard,
        "guard_observation_status": "OBSERVED" if guard is not None else "UNKNOWN",
        "summary": None,
    }
    if summary is not None:
        # No arguments, file contents, provider URLs, paths from approvals, or
        # unconstrained model text are copied out of the canonical diagnostics.
        keep = (
            "model", "model_settings", "tool_hint_mode", "max_iterations",
            "projection", "event_counts", "target_exists", "usage",
            "tool_calls", "approval_count",
            "stripped_stray_tool_markup",
        )
        projected["summary"] = {key: summary[key] for key in keep if key in summary}
        projected["summary"]["completion_guard"] = guard
        projected["summary"]["suppressed_batch_count"] = len(summary.get("suppressed_speculative_batches", []))
        projected["summary"]["unprojected_call_count"] = len(summary.get("unprojected_tool_calls", []))
    if guard is not None:
        require(guard.get("mode") == mode, "completion_mode_observation")
        require(type(guard.get("nudges")) is int and 0 <= guard["nudges"] <= 1, "bounded_completion_nudges")
        require(type(guard.get("required_output_count")) is int and
                0 <= guard["required_output_count"] <= 16, "guard_output_count")
        requirement_hash = guard.get("requirements_sha256")
        require(isinstance(requirement_hash, str) and requirement_hash.startswith("sha256:") and
                len(requirement_hash) == 71 and all(c in "0123456789abcdef" for c in requirement_hash[7:]),
                "guard_requirement_identity")
        if mode == "none":
            require(guard["nudges"] == 0, "disabled_guard_nudged")
        if guard["nudges"]:
            require(nudge is not None, "missing_nudge_marker")
    if nudge is not None:
        require(guard is not None and nudge.get("nudges") == guard["nudges"] == 1,
                "completion_summary_join")
        for key in ("mode", "required_output_count", "requirements_sha256"):
            require(nudge.get(key) == guard.get(key), "completion_marker_binding")
        projected["nudge_marker"] = {key: nudge[key] for key in guard_keys if key in nudge}
    return projected


def verify_snapshot(directory, task, accepted):
    """Recheck the same public canonical oracle; never send it to the actor."""
    snapshot = directory / "snapshot"
    manifest = json.loads((snapshot / "snapshot_manifest.json").read_bytes())
    require(set(manifest["files"]) == set(TASK_OUTPUTS[task]), "snapshot_members")
    for name, record in manifest["files"].items():
        path = snapshot / name
        require(record["present"] == path.is_file(), "snapshot_presence")
        if record["present"]:
            require(record["size_bytes"] == path.stat().st_size and
                    record["sha256"] == file_digest(path), "snapshot_digest")
    verifier = ROOT / "qualification/tasks" / task / "verify.py"
    result = subprocess.run([sys.executable, str(verifier), str(snapshot)],
                            capture_output=True, timeout=SNAPSHOT_VERIFIER_TIMEOUT_S)
    require(result.returncode in (0, 1), "snapshot_verifier_error")
    if accepted:
        require(result.returncode == 0, "accepted_snapshot_mismatch")
    return {"verifier_exit_code": result.returncode,
            "stdout_digest": digest(result.stdout), "stderr_digest": digest(result.stderr)}


def validate_observed_configuration(diagnostics, observation, candidate):
    """Reject contradictory settings; preserve missing failed-attempt telemetry."""
    missing = []
    workload = observation.get("workload") or {}
    for key in ("configured_max_iterations", "model_calls_started"):
        value = workload.get(key)
        if value is None:
            missing.append(key)
        elif key == "configured_max_iterations":
            require(type(value) is int and value == 4, "unchanged_iteration_limit")
        else:
            require(type(value) is int and 0 <= value <= 4, "total_model_call_budget")
    summary = diagnostics.get("summary")
    if summary is None:
        missing.append("adapter_summary")
    else:
        expected_settings = {"parallel_tool_calls": False, "max_tokens": 256,
                             "reasoning_effort": "none", "extra_body": EXTRA_BODY}
        for key, expected in (
            ("model", "local-openai:completion-guard"),
            ("max_iterations", 4), ("model_settings", expected_settings),
            ("tool_hint_mode", "none"), ("projection", candidate["toolset"]),
        ):
            if key not in summary:
                missing.append("adapter_" + key)
            else:
                require(summary[key] == expected, "observed_configuration_" + key)
    if diagnostics.get("guard_observation") is None:
        missing.append("completion_guard")
    if observation["success"]:
        require(not missing, "accepted_attempt_missing_configuration_evidence")
    return missing


class Native:
    def __init__(self, directory, server, model):
        self.directory, self.server, self.model = directory, server, model
        self.process = None
        self.startup_s = None
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]

    def start(self):
        started = time.monotonic()
        with (self.directory / "native.log").open("ab") as log:
            self.process = subprocess.Popen([
                str(self.server), "-m", str(self.model), "--alias", "completion-guard",
                "-c", "8192", "-np", "1", "-t", "4", "-ngl", "0", "--jinja",
                "--cache-ram", "0", "--no-cache-idle-slots",
                "--host", "127.0.0.1", "--port", str(self.port),
            ], stdout=log, stderr=log)
        deadline = started + HEALTH_TIMEOUT_S
        while time.monotonic() < deadline:
            require(self.process.poll() is None, "native_process_exited")
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://127.0.0.1:{self.port}/health", timeout=1) as response:
                    require(json.load(response).get("status") == "ok", "native_health")
                self.startup_s = time.monotonic() - started
                return
            except OSError:
                time.sleep(0.25)
        raise RuntimeError("native_readiness_timeout")

    def stop(self):
        started = time.monotonic()
        forced = False
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=TEARDOWN_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    forced = True
                    self.process.kill()
                    self.process.wait(timeout=TEARDOWN_TIMEOUT_S)
            return {"pid": self.process.pid, "exit_code": self.process.returncode,
                    "forced_kill": forced, "teardown_s": time.monotonic()-started,
                    "process_stopped": self.process.poll() is not None}
        return {"pid": None, "exit_code": None, "forced_kill": forced,
                "teardown_s": time.monotonic()-started, "process_stopped": True}


def run_arm(out, rep, task, mode, order, venv, source, source_files, server, model):
    directory = out / task / mode
    directory.mkdir(parents=True)
    native = Native(directory, server, model)
    started = time.monotonic()
    row = {"rep": rep, "task": task, "completion_check": mode, "order": order,
           "status": "INFRA_FAILURE", "accepted": None}
    try:
        task_dir = ROOT / "qualification/tasks" / task
        task_hash = tree_digest(task_dir)
        candidate = candidate_metadata(task, mode, task_hash, source_files)
        requirements = TASK_OUTPUTS[task]
        packet = {
            "schema": "completion-guard-resident-pilot/v1", "source": source,
            "launch_id": f"{os.environ['GITHUB_RUN_ID']}-{rep}-{task}-{mode}",
            "task": task, "task_package_digest": task_hash, "completion_check": mode,
            "model_manifest": MODEL_MANIFEST, "model_blob": MODEL_BLOB,
            "harness": HARNESS, "server_revision": LLAMA_REV,
            "server_binary_digest": file_digest(server), "source_files": source_files,
        }
        experiment = experiment_metadata(task, mode, rep)
        validate_schema(experiment, "experiment.schema.json")
        write(directory / "packet.json", packet)
        write(directory / "candidate.json", candidate)
        write(directory / "experiment.json", experiment)
        native.start()
        candidate_env = {
            "MODEL_SPELUNKER_MODEL": "local-openai:completion-guard",
            "MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": f"http://127.0.0.1:{native.port}/v1",
            "MODEL_SPELUNKER_MAX_ITERATIONS": "4",
            "MODEL_SPELUNKER_MAX_TOKENS": "256",
            "MODEL_SPELUNKER_REASONING_EFFORT": "none",
            "MODEL_SPELUNKER_TOOL_HINT_MODE": "none",
            "MODEL_SPELUNKER_EXTRA_BODY": json.dumps(EXTRA_BODY, sort_keys=True),
            "MODEL_SPELUNKER_COMPLETION_CHECK": mode,
            "MODEL_SPELUNKER_REQUIRED_OUTPUT_PATHS": json.dumps(requirements),
        }
        env = {k: v for k, v in os.environ.items()
               if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        env.update(candidate_env)
        command = [
            sys.executable, str(ROOT / "qualification/run_task.py"),
            "--task-commit", source, "--substrate-profile-id", "completion-guard-public-cpu-r0",
            "--substrate-profile-commit", source, "--timeout-override", str(TASK_WALL_TIMEOUT_S),
            "--experiment", str(directory / "experiment.json"),
            "--launch-id", packet["launch_id"],
            "--launch-packet-digest", canonical_json_digest(packet),
            "--snapshot-dir", str(directory / "snapshot"),
            "--diagnostics", str(directory / "diagnostics.raw"),
        ]
        for key in candidate_env:
            command.extend(("--pass-env", key))
        command.extend((str(task_dir), str(directory / "candidate.json"),
                        str(directory / "receipt.json"), "--", str(venv / "bin/python"),
                        str(ROOT / "qualification/adapters/openworker_projected.py")))
        result = subprocess.run(command, env=env, capture_output=True, timeout=RUNNER_TIMEOUT_S)
        row.update(runner_exit=result.returncode, runner_stdout_digest=digest(result.stdout),
                   runner_stderr_digest=digest(result.stderr))
        receipt_raw = (directory / "receipt.json").read_bytes()
        receipt = json.loads(receipt_raw)
        validate_schema(receipt, "run-receipt.schema.json")
        obs = receipt["observation"]
        require(receipt["task"]["id"] == task and receipt["task"]["source_commit"] == source and
                receipt["task"]["package_digest"] == task_hash, "task_source_binding")
        require(receipt["launch"] == {"launch_id": packet["launch_id"],
                "packet_digest": canonical_json_digest(packet)}, "launch_binding")
        require(receipt["candidate"]["configuration_digest"] == canonical_json_digest(candidate),
                "candidate_binding")
        require(all(receipt["candidate"][key] == candidate[key] for key in ("harness", "model", "toolset")),
                "candidate_identity_projection")
        require(receipt["substrate"] == {"profile_id": "completion-guard-public-cpu-r0",
                "profile_commit": source}, "substrate_binding")
        require(receipt["experiment"]["digest"] == canonical_json_digest(experiment), "experiment_binding")
        require(type(obs["success"]) is bool and result.returncode == (0 if obs["success"] else 1),
                "canonical_acceptance")
        if obs["success"]:
            require(obs["candidate_exit_code"] == obs["verifier_exit_code"] == 0 and not obs["timed_out"],
                    "accepted_exit_codes")
        snapshot_check = verify_snapshot(directory, task, obs["success"])
        diagnostics_raw = json.loads((directory / "diagnostics.raw").read_bytes())
        diagnostics = project_diagnostics(diagnostics_raw, mode)
        guard = diagnostics["guard_observation"]
        if mode == "required-files-v1" and guard is not None:
            require(guard.get("required_output_count") == len(requirements), "required_output_count")
            require(guard.get("requirements_sha256") == canonical_json_digest(requirements),
                    "requirements_digest")
        missing_configuration = validate_observed_configuration(diagnostics, obs, candidate)
        write(directory / "diagnostics.json", diagnostics)
        row.update(
            status="OBSERVED", accepted=obs["success"], run_id=receipt["run_id"],
            receipt_sha256=digest(receipt_raw), task_wall_s=obs["wall_seconds"],
            termination_class=obs["termination_class"], failure_class=obs["failure_class"],
            task_package_digest=task_hash, snapshot_check=snapshot_check,
            guard_observation_status=diagnostics["guard_observation_status"],
            completion_guard=guard, observation=obs,
            configuration_observation_status="UNKNOWN" if missing_configuration else "OBSERVED",
            missing_configuration_fields=missing_configuration,
            provider_reported_token_counts={key: obs.get(key) for key in
                ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")},
        )
    except Exception as exc:
        row["error"] = type(exc).__name__ + ":" + str(exc)[:180]
    finally:
        row["startup_s"] = native.startup_s
        try:
            row["teardown"] = native.stop()
        except Exception as exc:
            row["teardown"] = {"process_stopped": False, "error_type": type(exc).__name__}
            row["status"] = "INFRA_FAILURE"
        row["total_wall_s"] = time.monotonic() - started
        write(directory / "result.json", row)
    return row


def self_test():
    # Check the experiment's meaningful treatment isolation and output evidence
    # fail-closed seam without installing a harness or performing inference.
    for task in TASK_OUTPUTS:
        source_files = {"fixture": "sha256:" + "a"*64}
        a = candidate_metadata(task, ARMS[0], "sha256:" + "b"*64, source_files)
        b = candidate_metadata(task, ARMS[1], "sha256:" + "b"*64, source_files)
        require(a != b, "treatment_digest_distinct")
        b["configuration"]["completion_check"] = "none"
        require(a == b, "unplanned_candidate_difference")
        for mode in ARMS:
            validate_schema(experiment_metadata(task, mode, 0), "experiment.schema.json")
    starts = [ordered_arms(rep, task)[0] for rep in range(3) for task in TASK_OUTPUTS]
    require(starts.count(ARMS[0]) == starts.count(ARMS[1]) == 3, "paired_order_balance")
    guard = {"mode": "required-files-v1", "nudges": 1, "required_output_count": 1,
             "requirements_sha256": canonical_json_digest(["result.json"])}
    summary = {"completion_guard": guard, "approvals": [{"path": "do-not-export"}]}
    raw = {"candidate_stdout_tail": "OPENWORKER_SUMMARY="+json.dumps(summary)+"\nMODEL_SPELUNKER_COMPLETION_GUARD="+json.dumps(guard)}
    projection = project_diagnostics(raw, "required-files-v1")
    require("approvals" not in projection["summary"], "diagnostic_allowlist")
    disabled = {"mode": "none", "nudges": 0, "required_output_count": 0,
                "requirements_sha256": canonical_json_digest([])}
    project_diagnostics({"candidate_stdout_tail": "OPENWORKER_SUMMARY=" +
                         json.dumps({"completion_guard": disabled})}, "none")
    unknown = {"summary": None, "guard_observation": None}
    require(bool(validate_observed_configuration(unknown, {"success": False}, a)),
            "missing_failed_attempt_telemetry_not_preserved")
    try:
        validate_observed_configuration(unknown, {"success": True}, a)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted_without_configuration_evidence")
    try:
        validate_observed_configuration(unknown, {"success": False,
            "workload": {"model_calls_started": 5}}, a)
    except ValueError:
        pass
    else:
        raise AssertionError("excess_call_budget_accepted")
    for mode, payload in [
        ("none", raw),
        ("required-files-v1", {"candidate_stdout_tail": "OPENWORKER_SUMMARY={}\nMODEL_SPELUNKER_COMPLETION_GUARD="+json.dumps(guard)}),
        ("required-files-v1", {"candidate_stdout_tail": "MODEL_SPELUNKER_COMPLETION_GUARD=[]"}),
        ("required-files-v1", {"candidate_stdout_tail": "OPENWORKER_SUMMARY="+json.dumps(summary)}),
    ]:
        try:
            project_diagnostics(payload, mode)
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError("invalid_diagnostics_accepted")
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        snapshot = directory / "snapshot"
        snapshot.mkdir()
        (snapshot / "value.txt").write_bytes(b"READY\n")
        write(snapshot / "snapshot_manifest.json", {"files": {"value.txt": {
            "present": True, "size_bytes": 6, "sha256": digest(b"READY\n")}}})
        verify_snapshot(directory, "text-repair-v0", True)
        (snapshot / "value.txt").write_bytes(b"WRONG\n")
        try:
            verify_snapshot(directory, "text-repair-v0", True)
        except ValueError:
            pass
        else:
            raise AssertionError("modified_snapshot_accepted")
    print("PASS treatment isolation, paired order, diagnostics joins, and snapshot corruption rejection")


def provider_self_test():
    """Prove the pinned installed provider forwards native extras without a relay."""
    from coworker.providers.openai_provider import OpenAIProvider
    captured = []
    class Completions:
        def create(self, **kwargs):
            captured.append(kwargs)
            return iter(())
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = OpenAIProvider(client=client)
    list(provider.stream(model="completion-guard", messages=[{"role": "user", "content": "synthetic"}],
                         max_tokens=256, parallel_tool_calls=False, reasoning_effort="none",
                         extra_body=EXTRA_BODY))
    require(len(captured) == 1 and captured[0]["extra_body"] == EXTRA_BODY, "provider_extra_body")
    require(captured[0]["max_tokens"] == 256 and captured[0]["stream"] is True, "provider_settings")
    print("PASS pinned provider extra_body forwarding; no network request or model inference")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--provider-self-test", action="store_true")
    parser.add_argument("--rep", type=int)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--venv", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.provider_self_test:
        provider_self_test()
        return
    require(args.rep in range(3) and args.out is not None and args.venv is not None, "experiment_arguments")
    source = os.environ.get("GITHUB_SHA", "")
    require(len(source) == 40 and all(c in "0123456789abcdef" for c in source), "exact_source_required")
    require(os.environ.get("LLAMA_REV") == LLAMA_REV, "server_revision")
    model = Path(os.environ["COMPLETION_GUARD_MODEL"]).resolve()
    server = Path(os.environ["COMPLETION_GUARD_SERVER"]).resolve()
    require(file_digest(model) == MODEL_BLOB, "model_identity")
    require(os.environ["COMPLETION_GUARD_MODEL_BLOB_DIGEST"] == MODEL_BLOB, "hydrated_model_binding")
    source_files = {path: file_digest(ROOT / path) for path in SOURCE_PATHS}
    out = args.out.resolve()
    out.mkdir(parents=True)
    rows = []
    for task in ordered_tasks(args.rep):
        for order, mode in enumerate(ordered_arms(args.rep, task)):
            rows.append(run_arm(out, args.rep, task, mode, order, args.venv.resolve(),
                                source, source_files, server, model))
    write(out / "summary.json", {
        "schema": "completion-guard-resident-summary/v1", "scope": "FRAMEWORK_PROVING_ONLY",
        "source": source, "rep": args.rep, "planned_attempts": 4, "rows": rows,
        "model_manifest": MODEL_MANIFEST, "model_blob": MODEL_BLOB,
        "server_revision": LLAMA_REV, "source_files": source_files,
        "promotion_authorized": False,
        "limitations": [
            "public CPU synthetic tasks, three exploratory paired blocks per task",
            "repeated accepted attempts are not unique production deliverables",
            "full wall includes server startup, task, external verification, and teardown",
            "build and model hydration are outside per-arm wall; no campaign makespan claim",
            "native token counts flow through the pinned provider into canonical receipts",
            "raw model requests, responses, native logs, and raw diagnostics are not uploaded",
            "task failure and zero treatment gain are valid preserved observations",
        ],
    })
    require(len(rows) == 4 and all(row["status"] == "OBSERVED" for row in rows),
            "incomplete_infrastructure_or_evidence")
    require(len({row["run_id"] for row in rows}) == 4, "distinct_canonical_attempts")
    require(all(row["teardown"]["process_stopped"] for row in rows), "native_teardown")


if __name__ == "__main__":
    main()

