#!/usr/bin/env python3
"""One fixed inference case on an existing native artifact producer and consumer.

The accepted native_build_reuse_r0 helpers own packaging and transfer admission.
This file adds model/harness hydration and an unchanged canonical task. It is
not a serving framework, model selector, deployment tool, or speedup benchmark.
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
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from qualification.run_task import canonical_json_digest, tree_digest
from qualification.serving_fanout_r0.native_build_reuse_r0 import proof as reuse

HARNESS_REV = "5bc10d928e0b64aae74313349a3b17bd19643ae2"
HARNESS = "ghcr.io/sempersupra/model-spelunker-harness-openworker@sha256:e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83"
ADMISSION_PATH = "qualification/harness-artifacts/openworker-5bc10d928e0b-linux-x64.admission-v2.json"
MODEL_MANIFEST = "sha256:8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
MODEL_BLOB = "sha256:3d0b790534fe4b79525fc3692950408dca41171676ed7e21db57af5c65ef6ab6"
MODEL_BYTES = 1_359_279_776
OLLAMA_VERSION = "0.34.1"
OLLAMA_ARCHIVE = "sha256:f361dc3992ec07e4ad429f4bb2d10d4663ba2c295f9a9a688c7d52f4ba650034"
TASK = ROOT / "qualification/tasks/text-repair-v0"
ALIAS = "native-inference-reuse"
TIMEOUTS = {"task_s": 240, "runner_s": 300, "readiness_s": 60,
            "teardown_s": 10, "snapshot_verifier_s": 15}
EXTRA_BODY = {"seed": 42, "temperature": 0, "id_slot": 0, "cache_prompt": True,
              "chat_template_kwargs": {"enable_thinking": False}}
SETTINGS = {"parallel_tool_calls": False, "max_tokens": 256,
            "reasoning_effort": "none", "extra_body": EXTRA_BODY}
SERVER_FLAGS = ["-c", "8192", "-np", "1", "-t", "4", "-ngl", "0", "--jinja",
                "--cache-ram", "0", "--no-cache-idle-slots"]
SOURCE_PATHS = (
    "qualification/run_task.py", "qualification/run-receipt.schema.json",
    "qualification/adapters/openworker_projected.py",
    "qualification/adapters/local_openai_route.py",
    "qualification/adapters/tool_result_observations.py",
    "qualification/adapters/tool_repeat_limit.py",
    "qualification/serving_fanout_r0/native_build_reuse_r0/proof.py",
    "qualification/serving_fanout_r0/native_inference_reuse_r0/proof.py",
    "qualification/serving_fanout_r0/native_inference_reuse_r0/test_proof.py",
    ".github/workflows/native-inference-reuse-r0.yml", ADMISSION_PATH,
)
require, sha, write = reuse.require, reuse.sha, reuse.write


def clean_environment():
    return {key: value for key, value in os.environ.items()
            if key.lower() not in ("http_proxy", "https_proxy", "all_proxy")
            and not key.startswith(("MODEL_SPELUNKER_", "LD_"))}


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def get_json(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return json.load(response)


def wait_ready(process, url, check):
    started = time.monotonic()
    while time.monotonic() - started < TIMEOUTS["readiness_s"]:
        require(process.poll() is None, "server_exited_before_readiness")
        try:
            if check(get_json(url)):
                return time.monotonic() - started
        except OSError:
            pass
        time.sleep(0.25)
    raise ValueError("server_readiness_timeout")


def stop_process(process):
    started = time.monotonic()
    forced = False
    running = process is not None and process.poll() is None
    if running:
        process.terminate()
        try:
            process.wait(timeout=TIMEOUTS["teardown_s"])
        except subprocess.TimeoutExpired:
            forced = True
            process.kill()
            try:
                process.wait(timeout=TIMEOUTS["teardown_s"])
            except subprocess.TimeoutExpired:
                pass  # Retain the incomplete teardown instead of losing the report.
    return {"process_stopped": process is None or process.poll() is not None,
            "running_before_owned_shutdown": running,
            "forced_kill": forced, "exit_code": None if process is None else process.returncode,
            "elapsed_s": time.monotonic() - started}


def model_contract(manifest, manifest_digest, blob_digest, blob_bytes, magic):
    require(manifest_digest == MODEL_MANIFEST, "model_manifest_digest")
    layers = [row for row in manifest["layers"]
              if row.get("mediaType") == "application/vnd.ollama.image.model"]
    require(len(layers) == 1, "single_model_layer")
    require(layers[0]["digest"] == blob_digest == MODEL_BLOB, "model_blob_digest")
    require(type(layers[0]["size"]) is int and
            layers[0]["size"] == blob_bytes == MODEL_BYTES, "model_blob_size")
    require(magic == b"GGUF", "model_format")
    return {"manifest_sha256": manifest_digest, "blob_sha256": blob_digest,
            "bytes": blob_bytes, "format": "GGUF"}


def verify_model(root):
    manifest = root / "manifests/registry.ollama.ai/library/qwen3/1.7b"
    blob = root / "blobs" / MODEL_BLOB.replace(":", "-")
    with blob.open("rb") as stream:
        magic = stream.read(4)
    identity = model_contract(json.loads(manifest.read_bytes()), sha(manifest),
                              sha(blob), blob.stat().st_size, magic)
    return blob, identity


def prepare(args):
    """Hydrate immutable public inputs; the hydration server never runs inference."""
    out = args.out.resolve()
    out.mkdir(parents=True)
    result = {"schema": "native-inference-inputs/v1", "status": "FAIL", "timings": {}}
    started = time.monotonic()
    hydration = None
    try:
        stage = time.monotonic()
        harness = out / "harness"
        harness.mkdir()
        reuse.command(["docker", "pull", HARNESS], timeout=300, log=out / "harness-pull.log")
        container, _, _ = reuse.command(["docker", "create", HARNESS, "/artifact/noop"])
        try:
            reuse.command(["docker", "cp", container.strip() + ":/artifact/.", str(harness)], timeout=90)
        finally:
            reuse.command(["docker", "rm", container.strip()])
        admission = json.loads((ROOT / ADMISSION_PATH).read_bytes())
        receipt_path = harness / "build-receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        require(admission["artifact"]["ref"] == HARNESS and
                admission["artifact"]["build_receipt_digest"] == sha(receipt_path), "harness_admission")
        require(receipt["harness"]["name"] == "openworker" and
                receipt["source"]["revision"] == HARNESS_REV, "harness_source")
        for row in receipt["payload"]["files"]:
            path = (harness / row["path"]).resolve()
            require(path.is_relative_to(harness) and path.is_file(), "harness_payload_path")
            require(path.stat().st_size == row["bytes"] and sha(path) == "sha256:" + row["sha256"],
                    "harness_payload_digest")
        venv = out / "venv"
        reuse.command([sys.executable, "-m", "venv", str(venv)], timeout=60)
        wheels = sorted(str(path) for path in (harness / "wheelhouse").glob("*.whl"))
        require(wheels, "harness_wheelhouse")
        reuse.command([str(venv / "bin/pip"), "install", "--disable-pip-version-check", "--no-index",
                       "--no-deps", *wheels], timeout=120, log=out / "harness-install.log")
        reuse.command([str(venv / "bin/python"), "-c", "import coworker, coworker.engine"], timeout=30)
        result["harness"] = {"ref": HARNESS, "revision": HARNESS_REV,
                             "build_receipt_digest": sha(receipt_path)}
        result["timings"]["harness_hydration_s"] = time.monotonic() - stage
        stage = time.monotonic()
        archive = out / "ollama-linux-amd64.tar.zst"
        reuse.command(["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3",
                       f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_VERSION}/ollama-linux-amd64.tar.zst",
                       "--output", str(archive)], timeout=300, log=out / "ollama-download.log")
        require(sha(archive) == OLLAMA_ARCHIVE, "hydration_runtime_digest")
        runtime = out / "ollama-runtime"
        runtime.mkdir()
        reuse.command(["tar", "--use-compress-program=unzstd", "-xf", str(archive), "-C", str(runtime)],
                      timeout=120, log=out / "ollama-unpack.log")
        model_root = out / "models"
        model_root.mkdir()
        port = free_port()
        env = clean_environment()
        env.update(OLLAMA_HOST=f"127.0.0.1:{port}", OLLAMA_MODELS=str(model_root))
        ollama = str(runtime / "bin/ollama")
        with (out / "hydration.log").open("wb") as log:
            hydration = subprocess.Popen([ollama, "serve"], env=env, stdout=log, stderr=log)
        wait_ready(hydration, f"http://127.0.0.1:{port}/api/tags", lambda value: "models" in value)
        reuse.command([ollama, "pull", "qwen3:1.7b"], env=env, timeout=600, log=out / "model-pull.log")
        _, result["model"] = verify_model(model_root)
        result["timings"]["model_hydration_and_integrity_s"] = time.monotonic() - stage
        result["status"] = "READY"
    except Exception as exc:
        result["failure"] = type(exc).__name__ + ":" + str(exc)[:180]
        raise
    finally:
        result["hydration_teardown"] = stop_process(hydration)
        if (not result["hydration_teardown"]["process_stopped"] or
                not result["hydration_teardown"]["running_before_owned_shutdown"] or
                result["hydration_teardown"]["forced_kill"]):
            result["status"] = "FAIL"
            result.setdefault("failure", "ValueError:hydration_teardown")
        result["timings"]["prepare_total_s"] = time.monotonic() - started
        write(out / "setup.json", result)
    require(result["hydration_teardown"]["process_stopped"] and
            result["hydration_teardown"]["running_before_owned_shutdown"] and
            not result["hydration_teardown"]["forced_kill"], "hydration_teardown")


def source_witness(identity):
    head, _, _ = reuse.command(["git", "rev-parse", "HEAD"], cwd=ROOT)
    require(head.strip() == identity["source_commit"], "checkout_source")
    paths = [*SOURCE_PATHS, *(str(path.relative_to(ROOT)) for path in TASK.rglob("*") if path.is_file())]
    witnesses = {}
    for name in paths:
        content = subprocess.run(["git", "cat-file", "blob", "HEAD:" + name], cwd=ROOT,
                                 check=True, capture_output=True, timeout=10).stdout
        require((ROOT / name).read_bytes() == content, "source_bytes:" + name)
        witnesses[name] = "sha256:" + hashlib.sha256(content).hexdigest()
    tree, _, _ = reuse.command(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT)
    return {"commit": head.strip(), "tree": tree.strip(), "files": witnesses}


def schema_check(value, name):
    from jsonschema import Draft7Validator
    Draft7Validator(json.loads((ROOT / "qualification" / name).read_bytes())).validate(value)


def snapshot_check(directory):
    snapshot = directory / "snapshot"
    manifest = json.loads((snapshot / "snapshot_manifest.json").read_bytes())
    require(set(manifest["files"]) == {"value.txt"}, "snapshot_members")
    row = manifest["files"]["value.txt"]
    path = snapshot / "value.txt"
    require(row["present"] is True and path.is_file() and not path.is_symlink(), "snapshot_presence")
    require(row["size_bytes"] == path.stat().st_size and row["sha256"] == sha(path), "snapshot_digest")
    started = time.monotonic()
    verified = subprocess.run([sys.executable, str(TASK / "verify.py"), str(snapshot)],
                              capture_output=True, timeout=TIMEOUTS["snapshot_verifier_s"])
    require(verified.returncode == 0, "independent_snapshot_oracle")
    return {"exit_code": verified.returncode, "elapsed_s": time.monotonic() - started,
            "output_sha256": sha(path), "manifest_sha256": sha(snapshot / "snapshot_manifest.json")}


def check_receipt(receipt, candidate, packet, experiment, runner_exit):
    schema_check(receipt, "run-receipt.schema.json")
    source = packet["source"]["commit"]
    require(receipt["task"]["id"] == "text-repair-v0" and receipt["task"]["source_commit"] == source and
            receipt["task"]["package_digest"] == packet["task_package_digest"], "receipt_task_join")
    require(receipt["launch"] == {"launch_id": packet["launch_id"],
            "packet_digest": canonical_json_digest(packet)}, "receipt_launch_join")
    require(receipt["candidate"]["configuration_digest"] == canonical_json_digest(candidate), "receipt_config_join")
    require(all(receipt["candidate"][key] == candidate[key] for key in ("harness", "model", "toolset")),
            "receipt_candidate_join")
    require(receipt["substrate"] == {"profile_id": "native-inference-public-cpu-r0", "profile_commit": source},
            "receipt_substrate_join")
    require(receipt["experiment"]["digest"] == canonical_json_digest(experiment), "receipt_experiment_join")
    observation = receipt["observation"]
    require(runner_exit == 0 and observation["success"] is True and
            observation["candidate_exit_code"] == observation["verifier_exit_code"] == 0 and
            not observation["timed_out"], "canonical_task_not_accepted")
    require(observation.get("engine_error_types") == [], "inference_engine_error")
    workload = observation.get("workload", {})
    require(workload.get("configured_max_iterations") == 4 and
            type(workload.get("model_calls_started")) is int and
            1 <= workload["model_calls_started"] <= 4, "receipt_call_budget")
    require("tool_result_observations" in workload, "missing_native_tool_observations")
    return observation


def adapter_settings(raw):
    lines = [line[len("OPENWORKER_SUMMARY="):] for line in raw["candidate_stdout_tail"].splitlines()
             if line.startswith("OPENWORKER_SUMMARY=")]
    require(len(lines) == 1, "unique_adapter_summary")
    summary = json.loads(lines[0])
    expected = {"model": "local-openai:" + ALIAS, "model_settings": SETTINGS,
                "tool_hint_mode": "none", "max_iterations": 4, "projection": ["read_file", "write_file"]}
    require(all(summary.get(key) == value for key, value in expected.items()), "adapter_configuration")
    require(summary.get("tool_repeat_limit", 0) == 0, "repeat_policy_must_remain_disabled")
    return expected


def compare_fixed_case(producer, consumer):
    require(producer["status"] == consumer["status"] == "ACCEPTED_FIXED_CASE", "pair_acceptance")
    for key in ("identity", "source", "model", "harness", "native_manifest_sha256", "server_binary_sha256", "server_revision",
                "server_flags", "task_package_digest", "settings", "timeouts", "chat_template_sha256",
                "chat_template_tool_use_sha256", "observed_server_configuration"):
        require(producer[key] == consumer[key], "producer_consumer_join:" + key)
    require(producer["role"] == "producer" and consumer["role"] == "consumer", "pair_roles")
    require(producer["snapshot"]["output_sha256"] == consumer["snapshot"]["output_sha256"], "pair_output")
    for row in (producer, consumer):
        require(row["teardown"]["process_stopped"] and row["teardown"]["running_before_owned_shutdown"] and
                not row["teardown"]["forced_kill"], "pair_teardown")
    return {"status": "VERIFIED_SAME_SUBSTRATE_FIXED_INFERENCE", "cases_per_side": 1,
            "claim": "One accepted fixed task on the producer and exact transferred consumer binary; no speedup or reliability estimate."}


def run_case(args):
    out, setup, server = args.out.resolve(), args.setup.resolve(), args.server.resolve()
    out.mkdir(parents=True)
    started = time.monotonic()
    process = None
    result = {"schema": "native-inference-case/v1", "role": args.role, "status": "FAIL", "timings": {}}
    failed = None
    try:
        prepared = json.loads((setup / "setup.json").read_bytes())
        require(prepared["status"] == "READY" and prepared["hydration_teardown"]["process_stopped"] and
                prepared["hydration_teardown"]["running_before_owned_shutdown"] and
                not prepared["hydration_teardown"]["forced_kill"], "hydration_not_quiescent")
        model, model_identity = verify_model(setup / "models")
        identity = reuse.expected_identity()
        source = source_witness(identity)
        payload = server.parent.parent
        native_manifest = reuse.validate_payload(payload, args.manifest_sha256, identity, reuse.substrate())
        require(server == payload / "bin/llama-server", "native_executable_path")
        require(reuse.dependencies(server.parent, native_manifest["native_files"]) ==
                native_manifest["dependencies"], "inference_dependency_contract")
        task_hash = tree_digest(TASK)
        port = free_port()
        server_env = reuse.environment(server.parent)
        with (out / "native.log").open("wb") as log:
            process = subprocess.Popen([str(server), "-m", str(model), "--alias", ALIAS, *SERVER_FLAGS,
                                        "--host", "127.0.0.1", "--port", str(port)],
                                       env=server_env, stdout=log, stderr=log)
        result["timings"]["native_readiness_s"] = wait_ready(
            process, f"http://127.0.0.1:{port}/health", lambda value: value.get("status") == "ok")
        props = get_json(f"http://127.0.0.1:{port}/props")
        template = props.get("chat_template")
        require(isinstance(template, str) and bool(template), "server_chat_template_missing")
        template_digest = "sha256:" + hashlib.sha256(template.encode()).hexdigest()
        tool_template = props.get("chat_template_tool_use")
        require(tool_template is None or isinstance(tool_template, str), "server_tool_template_type")
        tool_template_digest = (None if tool_template is None else
                                "sha256:" + hashlib.sha256(tool_template.encode()).hexdigest())
        observed_configuration = {"context_per_slot": props["default_generation_settings"]["n_ctx"],
                                  "slots": props["total_slots"], "alias": props["model_alias"]}
        require(observed_configuration == {"context_per_slot": 8192, "slots": 1, "alias": ALIAS},
                "observed_server_configuration")
        require(props["model_path"] == str(model), "loaded_model_path")
        models = get_json(f"http://127.0.0.1:{port}/v1/models")
        require([row["id"] for row in models["data"]] == [ALIAS], "served_model_alias")
        result.update(identity=identity, source=source, model=model_identity,
                      harness=prepared["harness"], native_manifest_sha256=args.manifest_sha256,
                      server_binary_sha256=sha(server), server_revision=reuse.REV,
                      server_flags=SERVER_FLAGS, task_package_digest=task_hash, settings=SETTINGS,
                      timeouts=TIMEOUTS, chat_template_sha256=template_digest,
                      chat_template_tool_use_sha256=tool_template_digest,
                      observed_server_configuration=observed_configuration)
        configuration = {"source_files": source["files"], "task_package_digest": task_hash,
                         "model_manifest": MODEL_MANIFEST, "server_binary_sha256": sha(server),
                         "server_revision": reuse.REV, "server_flags": SERVER_FLAGS,
                         "model_settings": SETTINGS, "max_iterations": 4, "timeouts": TIMEOUTS,
                         "tool_hint_mode": "none", "completion_guard": "none", "tool_repeat_limit": 0,
                         "chat_template_sha256": template_digest,
                         "chat_template_tool_use_sha256": tool_template_digest,
                         "observed_server_configuration": observed_configuration}
        candidate = {"harness": {"name": "openworker", "version": HARNESS_REV, "artifact_ref": HARNESS,
                     "admission_ref": f"github:SemperSupra/model-spelunker@{source['commit']}:{ADMISSION_PATH}"},
                     "model": {"provider": "local-openai", "id": ALIAS, "artifact_ref": MODEL_BLOB},
                     "toolset": ["read_file", "write_file"], "configuration": configuration}
        experiment = {"schema_version": 2, "id": "native-inference-reuse-r0",
                      "decision_question": "Does this exact transferred native binary retain one fixed task acceptance?",
                      "task": {"id": "text-repair-v0", "task_class": "software.bounded-repair"},
                      "actors": ["producer", "consumer"], "replication": {"reps_per_actor": 1,
                      "independent": False, "randomized_order": False}, "claim_type": "feasibility",
                      "experimental_role": "control" if args.role == "producer" else "replicate",
                      "primary_responses": ["accepted", "stage_wall_seconds"],
                      "stop_conditions": ["identity drift", "task rejection", "incomplete teardown"],
                      "exclusion_conditions": [], "variable_under_test": "fresh runner with transferred native artifact"}
        schema_check(experiment, "experiment.schema.json")
        packet = {"schema": "native-inference-launch/v1", "source": source,
                  "launch_id": identity["run_id"] + "-" + identity["run_attempt"] + "-" + args.role,
                  "task_package_digest": task_hash, "configuration_digest": canonical_json_digest(candidate)}
        for name, value in (("candidate", candidate), ("experiment", experiment), ("packet", packet)):
            write(out / (name + ".json"), value)
        env = clean_environment()
        actor_env = {"MODEL_SPELUNKER_MODEL": "local-openai:" + ALIAS,
                     "MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": f"http://127.0.0.1:{port}/v1",
                     "MODEL_SPELUNKER_MAX_ITERATIONS": "4", "MODEL_SPELUNKER_MAX_TOKENS": "256",
                     "MODEL_SPELUNKER_REASONING_EFFORT": "none", "MODEL_SPELUNKER_TOOL_HINT_MODE": "none",
                     "MODEL_SPELUNKER_EXTRA_BODY": json.dumps(EXTRA_BODY, sort_keys=True)}
        env.update(actor_env)
        command = [sys.executable, str(ROOT / "qualification/run_task.py"),
                   "--task-commit", source["commit"], "--substrate-profile-id", "native-inference-public-cpu-r0",
                   "--substrate-profile-commit", source["commit"], "--timeout-override", str(TIMEOUTS["task_s"]),
                   "--experiment", str(out / "experiment.json"), "--launch-id", packet["launch_id"],
                   "--launch-packet-digest", canonical_json_digest(packet),
                   "--snapshot-dir", str(out / "snapshot"), "--diagnostics", str(out / "diagnostics.raw")]
        for key in actor_env:
            command.extend(("--pass-env", key))
        command.extend((str(TASK), str(out / "candidate.json"), str(out / "receipt.json"), "--",
                        str(setup / "venv/bin/python"), str(ROOT / "qualification/adapters/openworker_projected.py")))
        stage = time.monotonic()
        run = subprocess.run(command, env=env, capture_output=True, timeout=TIMEOUTS["runner_s"])
        result["timings"]["canonical_runner_s"] = time.monotonic() - stage
        result["runner_exit"] = run.returncode
        (out / "runner.log").write_bytes(run.stdout + run.stderr)
        receipt = json.loads((out / "receipt.json").read_bytes())
        result["observation"] = check_receipt(receipt, candidate, packet, experiment, run.returncode)
        result["adapter_settings"] = adapter_settings(json.loads((out / "diagnostics.raw").read_bytes()))
        result["snapshot"] = snapshot_check(out)
        result["receipt_sha256"] = sha(out / "receipt.json")
        result["status"] = "ACCEPTED_FIXED_CASE"
    except Exception as exc:
        failed = exc
        result["failure"] = type(exc).__name__ + ":" + str(exc)[:180]
    finally:
        result["teardown"] = stop_process(process)
        result["timings"]["case_total_s"] = time.monotonic() - started
        if (not result["teardown"]["process_stopped"] or result["teardown"]["forced_kill"] or
                not result["teardown"]["running_before_owned_shutdown"]):
            result["status"] = "FAIL"
            failed = failed or ValueError("native_teardown")
            result.setdefault("failure", "ValueError:native_teardown")
        write(out / "case.json", result)
    if failed is not None:
        raise failed
    if args.producer_case:
        paired = compare_fixed_case(json.loads(args.producer_case.read_bytes()), result)
        write(out / "pair.json", paired)
    print(json.dumps({"role": args.role, "status": result["status"], "timings": result["timings"]}))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--out", type=Path, required=True)
    case = sub.add_parser("case")
    case.add_argument("--role", choices=("producer", "consumer"), required=True)
    case.add_argument("--setup", type=Path, required=True)
    case.add_argument("--server", type=Path, required=True)
    case.add_argument("--manifest-sha256", required=True)
    case.add_argument("--out", type=Path, required=True)
    case.add_argument("--producer-case", type=Path)
    args = parser.parse_args()
    require(args.mode != "case" or (args.role == "consumer") == bool(args.producer_case), "consumer_pair_required")
    (prepare if args.mode == "prepare" else run_case)(args)


if __name__ == "__main__":
    main()
