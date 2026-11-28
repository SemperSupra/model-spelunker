#!/usr/bin/env python3
"""Finite scripted HTTP/SSE qualification of the real adapter CLI, not model quality.

The witness wrapper only launches the child, preserves its exit/output, and copies
the public fixture tree. Neither a temporary cwd nor tool denial is OS isolation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading
import unittest
import venv


ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
TASK = ROOT / "qualification/tasks/validation-discovery-v0"
ADAPTER = ROOT / "qualification/adapters/openworker_projected.py"
HARNESS_SOURCE = "5bc10d928e0b64aae74313349a3b17bd19643ae2"
HARNESS_REF = "ghcr.io/sempersupra/model-spelunker-harness-openworker@sha256:e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83"
ENGINE_BLOB = "e492443c42a646ddfd86b36e9732b1e6c76042bf"
PROVIDER_BLOB = "3e7ca306b3926dd9538730157926ceae5c004e17"
MODEL = "synthetic-loopback"
TOOLS = {"list_files", "read_file", "write_file"}
RESULT = json.dumps({"entrypoint": "python scripts/validate.py"}) + "\n"
SENTINEL = "docs/VALIDATION.md"
MAX_BODY = 262144
MAX_RECORDS = 8
OPTIONS = None
NATIVE_IDENTITY = {}
CASE_RESULTS = {}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def snapshot_tree(root, destination):
    """Retain all public task bytes with finite bounds; never follow a link."""
    destination.mkdir(parents=True, exist_ok=False)
    files, total = {}, 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("fixture snapshot refuses links")
        if not path.is_file():
            continue
        data = path.read_bytes()
        total += len(data)
        if len(files) >= 64 or len(data) > 1048576 or total > 4194304:
            raise ValueError("fixture snapshot exceeds declared bound")
        relative = path.relative_to(root).as_posix()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files[relative] = {"bytes": len(data), "sha256": sha(data)}
    return files


def witness_child(command, instruction, evidence):
    """No adapter imports or hooks: forward the real child's output and status."""
    initial = snapshot_tree(Path.cwd(), evidence / "initial")
    write_json(evidence / "initial-files.json", initial)
    write_json(evidence / "child-start.json", {"cwd": str(Path.cwd()), "argv": command,
                                              "stdin_sha256": sha(instruction)})
    with (evidence / "adapter.stdout").open("wb") as stdout, (evidence / "adapter.stderr").open("wb") as stderr:
        child = subprocess.run(command, input=instruction, stdout=stdout, stderr=stderr, timeout=120)
    final = snapshot_tree(Path.cwd(), evidence / "final")
    write_json(evidence / "final-files.json", final)
    write_json(evidence / "child.json", {
        "argv": command, "exit_code": child.returncode, "stdin_sha256": sha(instruction),
        "adapter_sha256": sha(ADAPTER.read_bytes()), "wrapper_sha256": sha(SELF.read_bytes()),
        "scope": "PUBLIC_FIXTURE_WITNESS_NOT_OS_ISOLATION",
    })
    sys.stdout.buffer.write((evidence / "adapter.stdout").read_bytes())
    sys.stderr.buffer.write((evidence / "adapter.stderr").read_bytes())
    return child.returncode


def scripted_tool(name, arguments):
    return {"name": name, "arguments": arguments}


def script_for(case):
    allowed = scripted_tool("write_file", {"path": "result.json", "content": RESULT})
    if case == "permissions":
        return [scripted_tool("unprojected_tool", {"path": SENTINEL, "content": "DENIED"}),
                scripted_tool("write_file", {"path": SENTINEL, "content": "DENIED"}), allowed, None]
    if case == "repeat":
        # Different call IDs and JSON key order must not reset canonical-object identity.
        reordered = scripted_tool("write_file", {"content": RESULT, "path": "result.json"})
        return [allowed, reordered, copy.deepcopy(allowed),
                scripted_tool("write_file", {"path": "result.json", "content": "FOURTH_REQUEST_TRAP"})]
    raise ValueError("unknown finite script")


def response_bytes(case, index, action):
    identity = f"chatcmpl-{case}-{index}"
    common = {"id": identity, "object": "chat.completion.chunk", "created": 1, "model": MODEL}
    def chunk(delta, finish=None):
        return {**common, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    chunks = [chunk({"role": "assistant"})]
    if action is None:
        chunks += [chunk({"content": "Synthetic fixture complete."}), chunk({}, "stop")]
    else:
        arguments = json.dumps(action["arguments"], separators=(",", ":"))
        split = max(1, len(arguments) // 2)
        chunks += [chunk({"tool_calls": [{"index": 0, "id": f"call-{case}-{index}", "type": "function",
                                           "function": {"name": action["name"], "arguments": arguments[:split]}}]}),
                   chunk({"tool_calls": [{"index": 0, "function": {"arguments": arguments[split:]}}]}),
                   chunk({}, "tool_calls")]
    chunks.append({**common, "choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}})
    return b"".join(b"data: " + json.dumps(item).encode() + b"\n\n" for item in chunks) + b"data: [DONE]\n\n"


def validate_request(payload):
    if not isinstance(payload, dict) or payload.get("model") != MODEL or payload.get("stream") is not True:
        raise ValueError("unexpected model or transport")
    if type(payload.get("max_tokens")) is not int or payload["max_tokens"] != 256:
        raise ValueError("output budget drift")
    if payload.get("parallel_tool_calls") is not False:
        raise ValueError("parallel tool setting drift")
    tools = payload.get("tools")
    if not isinstance(tools, list) or len(tools) != 3:
        raise ValueError("tool projection size drift")
    names = [row.get("function", {}).get("name") for row in tools if isinstance(row, dict)]
    if set(names) != TOOLS or len(names) != len(set(names)):
        raise ValueError("tool projection drift")
    if not isinstance(payload.get("messages"), list):
        raise ValueError("messages missing")


class ScriptServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, case, evidence):
        super().__init__(("127.0.0.1", 0), ScriptHandler)
        self.case, self.evidence = case, evidence
        self.script, self.records, self.failures = script_for(case), [], []
        self.request_count = 0
        self.lock = threading.Lock()


class ScriptHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_POST(self):
        self.connection.settimeout(5)
        with self.server.lock:
            self.server.request_count += 1
            index = self.server.request_count
        record = {"index": index, "path": self.path, "authorization_is_placeholder":
                  self.headers.get("Authorization") == "Bearer local-no-auth"}
        status, response = 200, b""
        try:
            if self.path != "/v1/chat/completions" or index > len(self.server.script):
                raise ValueError("unexpected HTTP request")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                raise ValueError("request byte bound")
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("incomplete request")
            record["request_sha256"] = sha(raw)
            if index <= MAX_RECORDS:
                (self.server.evidence / f"request-{index}.json").write_bytes(raw)
            payload = json.loads(raw)
            validate_request(payload)
            if not record["authorization_is_placeholder"]:
                raise ValueError("unexpected authorization")
            if self.server.case == "repeat" and index == 3:
                # The actor is waiting for response three. Independently prove
                # output already passes before sending the rejected repeat.
                launch = json.loads((self.server.evidence.parent / "child-start.json").read_text())
                work = Path(launch["cwd"])
                prior = (work / "result.json").read_bytes()
                (self.server.evidence / "before-rejection-result.json").write_bytes(prior)
                oracle = subprocess.run([sys.executable, str(TASK / "verify.py"), str(work)],
                                        capture_output=True, timeout=5)
                record.update(prior_output_sha256=sha(prior), prior_oracle_exit=oracle.returncode)
                if prior != RESULT.encode() or oracle.returncode != 0:
                    raise ValueError("earlier output did not pass independent oracle")
            response = response_bytes(self.server.case, index, self.server.script[index - 1])
        except Exception as exc:
            status, response = 400, b'{"error":{"message":"finite fixture rejected request"}}'
            record["error_type"] = type(exc).__name__
            if len(self.server.failures) < MAX_RECORDS:
                self.server.failures.append(record)
        record["http_status"] = status
        record["response_sha256"] = sha(response)
        if index <= MAX_RECORDS:
            self.server.records.append(record)
            (self.server.evidence / f"response-{index}.sse").write_bytes(response)
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream" if status == 200 else "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(response)
        self.wfile.flush()
        self.close_connection = True


def marked(stdout, prefix):
    return [json.loads(line[len(prefix):]) for line in stdout.splitlines() if line.startswith(prefix)]


def native_python_path(path):
    # Resolving a venv executable's symlink selects the base interpreter.
    return path.absolute()


def source_provenance():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    paths = [
        "qualification/run_task.py", "qualification/run-receipt.schema.json",
        "qualification/endpoint_policy.py", "qualification/adapters/openworker_projected.py",
        "qualification/adapters/tool_repeat_limit.py", "qualification/adapters/tool_result_observations.py",
        "qualification/adapters/local_openai_route.py", "qualification/tests/test_openworker_loopback_native.py",
        ".github/workflows/openworker-tool-result-observations.yml",
        "qualification/harness-artifacts/openworker-5bc10d928e0b-linux-x64.admission-v2.json",
    ]
    paths += [p.relative_to(ROOT).as_posix() for p in sorted(TASK.rglob("*")) if p.is_file()]
    hashes = {}
    for relative in paths:
        raw = (ROOT / relative).read_bytes()
        blob = subprocess.check_output(["git", "cat-file", "blob", head + ":" + relative], cwd=ROOT)
        if raw != blob:
            raise ValueError("fixture source differs from tested Git bytes: " + relative)
        hashes[relative] = sha(raw)
    return {"source_commit": head, "source_sha256": hashes}


def native_identity(python):
    code = """import hashlib,importlib.metadata,inspect,json,platform,sys
from coworker.engine import TurnEngine
from coworker.providers.openai_provider import OpenAIProvider
def identity(cls):
 data=open(inspect.getsourcefile(cls),'rb').read()
 return {'sha256':hashlib.sha256(data).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\\0'+data).hexdigest()}
print(json.dumps({'engine':identity(TurnEngine),'provider':identity(OpenAIProvider),'openai_sdk':importlib.metadata.version('openai'),'python':sys.version,'platform':platform.system(),'machine':platform.machine()}))
"""
    probe = subprocess.run([str(python), "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=20)
    if probe.returncode:
        raise RuntimeError("required native artifact unavailable: " + probe.stderr[-2000:])
    identity = json.loads(probe.stdout)
    if (identity["engine"]["git_blob"] != ENGINE_BLOB or identity["provider"]["git_blob"] != PROVIDER_BLOB
            or identity["platform"] != "Linux" or identity["machine"] != "x86_64"):
        raise ValueError("native source/substrate identity mismatch")
    return identity


class ProtocolControls(unittest.TestCase):
    def test_native_python_argument_preserves_venv_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "native-venv"
            venv.EnvBuilder(with_pip=False, symlinks=True).create(root)
            python = native_python_path(root / "bin/python")
            actual = subprocess.check_output([str(python), "-c", "import sys;print(sys.prefix)"], text=True, timeout=10)
            self.assertEqual(Path(actual.strip()).resolve(), root.resolve())

    def test_sse_reassembles_fragmented_tool_arguments(self):
        for index, action in enumerate(script_for("repeat"), 1):
            raw = response_bytes("repeat", index, action)
            frames = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith(b"data: {")]
            calls = [c for f in frames for ch in f["choices"] for c in ch["delta"].get("tool_calls", [])]
            self.assertEqual(len(calls), 2)
            self.assertEqual(json.loads("".join(c["function"].get("arguments", "") for c in calls)), action["arguments"])
            self.assertEqual(calls[0]["id"], f"call-repeat-{index}")
            self.assertTrue(raw.endswith(b"data: [DONE]\n\n"))

    def test_wire_request_contract_rejects_budget_and_tool_drift(self):
        good = {"model": MODEL, "stream": True, "max_tokens": 256, "parallel_tool_calls": False,
                "tools": [{"function": {"name": name}} for name in sorted(TOOLS)], "messages": []}
        validate_request(good)
        for key, value in (("model", "other"), ("stream", False), ("max_tokens", True),
                           ("max_tokens", 257), ("parallel_tool_calls", True), ("tools", [])):
            with self.assertRaises(ValueError):
                validate_request({**good, key: value})

    def test_snapshot_preserves_bytes_and_rejects_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "work"
            root.mkdir()
            (root / "sentinel.txt").write_bytes(b"unchanged\r\n")
            manifest = snapshot_tree(root, Path(tmp) / "copy")
            self.assertEqual(manifest["sentinel.txt"]["sha256"], sha(b"unchanged\r\n"))
            self.assertEqual((Path(tmp) / "copy/sentinel.txt").read_bytes(), b"unchanged\r\n")
            (root / "link").symlink_to(root / "sentinel.txt")
            with self.assertRaises(ValueError):
                snapshot_tree(root, Path(tmp) / "links")

    def test_witness_forwards_nonzero_child_status_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, evidence = root / "work", root / "evidence"
            work.mkdir(); evidence.mkdir()
            (work / "sentinel").write_bytes(b"unchanged")
            # Exercise the same witness function with a real credential-free
            # subprocess. This is not a native adapter/model result.
            code = (f"import importlib.util; s=importlib.util.spec_from_file_location('fixture',{str(SELF)!r}); "
                    "m=importlib.util.module_from_spec(s);s.loader.exec_module(m); "
                    f"raise SystemExit(m.witness_child([{sys.executable!r},'-c',"
                    "\"import sys;print(sys.stdin.read());print('synthetic-error',file=sys.stderr);raise SystemExit(7)\"],"
                    f"b'input',m.Path({str(evidence)!r})))")
            result = subprocess.run([sys.executable, "-c", code], cwd=work, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(result.stdout, b"input\n")
            self.assertEqual(result.stderr, b"synthetic-error\n")
            self.assertEqual(json.loads((evidence / "child.json").read_text())["exit_code"], 7)
            self.assertEqual((evidence / "final/sentinel").read_bytes(), b"unchanged")


class NativeLoopbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global NATIVE_IDENTITY
        NATIVE_IDENTITY = native_identity(OPTIONS.native_python)
        cls.provenance = source_provenance()
        from jsonschema.validators import validator_for
        schema = json.loads((ROOT / "qualification/run-receipt.schema.json").read_text())
        validator = validator_for(schema)
        validator.check_schema(schema)
        cls.validator = validator(schema)

    def run_case(self, case):
        evidence = OPTIONS.evidence_dir / case
        evidence.mkdir()
        http = evidence / "http"
        http.mkdir()
        server = ScriptServer(case, http)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        task = json.loads((TASK / "task.json").read_text())
        self.assertEqual(task["limits"]["wall_seconds"], 120)
        metadata = {"harness": {"name": "openworker", "version": HARNESS_SOURCE, "artifact_ref": HARNESS_REF},
                    "model": {"provider": "local-openai", "id": MODEL}, "toolset": sorted(TOOLS),
                    "configuration": {"max_iterations": 4, "max_tokens": 256, "tool_repeat_limit": 2,
                                      "tool_hint_mode": "none", "provider": "FINITE_SCRIPT_NOT_A_MODEL"}}
        write_json(evidence / "candidate.json", metadata)
        settings = {"MODEL_SPELUNKER_MODEL": "local-openai:" + MODEL,
                    "MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                    "MODEL_SPELUNKER_MAX_ITERATIONS": "4", "MODEL_SPELUNKER_MAX_TOKENS": "256",
                    "MODEL_SPELUNKER_TOOL_REPEAT_LIMIT": "2", "MODEL_SPELUNKER_TOOL_HINT_MODE": "none"}
        # Deliberately do not inherit credentials, proxies, or provider defaults.
        environment = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", **settings}
        command = [sys.executable, str(ROOT / "qualification/run_task.py"),
                   "--task-commit", self.provenance["source_commit"],
                   "--substrate-profile-id", "public-linux-x64-native-loopback",
                   "--substrate-profile-commit", self.provenance["source_commit"],
                   "--snapshot-dir", str(evidence / "canonical-output")]
        for key in settings:
            command += ["--pass-env", key]
        command += [str(TASK), str(evidence / "candidate.json"), str(evidence / "receipt.json"), "--",
                    str(OPTIONS.native_python), str(SELF), "--actor", str(evidence)]
        try:
            result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, timeout=150)
            (evidence / "runner.stdout").write_bytes(result.stdout)
            (evidence / "runner.stderr").write_bytes(result.stderr)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
            write_json(evidence / "http-transcript.json", {"request_count": server.request_count,
                       "records": server.records, "failures": server.failures})
        self.assertFalse(thread.is_alive())
        self.assertEqual(server.failures, [])
        receipt = json.loads((evidence / "receipt.json").read_bytes())
        self.validator.validate(receipt)
        child = json.loads((evidence / "child.json").read_text())
        self.assertEqual(receipt["observation"]["candidate_exit_code"], child["exit_code"])
        self.assertFalse(receipt["observation"]["timed_out"])
        self.assertEqual(child["stdin_sha256"], sha((task["instruction"] + "\n").encode()))
        initial = json.loads((evidence / "initial-files.json").read_text())
        final = json.loads((evidence / "final-files.json").read_text())
        self.assertNotIn("verify.py", initial)
        self.assertNotIn("result.json", initial)
        self.assertEqual(set(final) - set(initial), {"result.json"})
        for path, witness in initial.items():
            self.assertEqual(final[path], witness, "scripted denial changed input/sentinel bytes")
        self.assertEqual((evidence / "final" / SENTINEL).read_bytes(), (TASK / "fixture" / SENTINEL).read_bytes())
        self.assertEqual((evidence / "final/result.json").read_bytes(), RESULT.encode())
        self.assertEqual((evidence / "canonical-output/result.json").read_bytes(), RESULT.encode())
        oracle = subprocess.run([sys.executable, str(TASK / "verify.py"), str(evidence / "final")],
                                capture_output=True, timeout=10)
        self.assertEqual(oracle.returncode, 0, "unchanged external oracle rejected scripted result")
        self.assertEqual(receipt["observation"]["verifier_exit_code"], 0)
        stdout = (evidence / "adapter.stdout").read_text(encoding="utf-8")
        events = marked(stdout, "OPENWORKER_EVENT=")
        starts = marked(stdout, "MODEL_SPELUNKER_MODEL_CALL_STARTED=")
        summaries = marked(stdout, "OPENWORKER_SUMMARY=")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["max_iterations"], 4)
        self.assertEqual(summaries[0]["model_settings"]["max_tokens"], 256)
        self.assertEqual(set(summaries[0]["projection"]), TOOLS)
        self.assertEqual(receipt["observation"]["workload"]["tool_result_observations"], summaries[0]["tool_result_observations"])
        requests = [json.loads((http / f"request-{i}.json").read_bytes()) for i in range(1, server.request_count + 1)]
        first_users = [m["content"] for m in requests[0]["messages"] if m.get("role") == "user"]
        self.assertEqual(first_users[-1], task["instruction"])
        self.assertNotIn("python scripts/validate.py", json.dumps(requests[0]["messages"]))
        for request in requests:
            validate_request(request)
        count = 4 if case == "permissions" else 3
        self.assertEqual(server.request_count, count)
        self.assertEqual([s["index"] for s in starts], list(range(1, count + 1)))
        expected_ids = [f"call-{case}-{i}" for i in range(1, count)]
        tool_messages = [m for m in requests[-1]["messages"] if m.get("role") == "tool"]
        self.assertEqual(len(tool_messages), count - 1)
        self.assertEqual([m["tool_call_id"] for m in tool_messages], expected_ids)
        CASE_RESULTS[case] = {"receipt_sha256": sha((evidence / "receipt.json").read_bytes()),
                              "run_id": receipt["run_id"], "http_requests": count,
                              "model_starts": len(starts), "child_exit": child["exit_code"],
                              "oracle_exit": oracle.returncode, "accepted": receipt["observation"]["success"]}
        return result, receipt, events, summaries[0], requests

    def test_unprojected_denied_and_allowed_tools_through_actual_cli(self):
        result, receipt, events, summary, requests = self.run_case("permissions")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(receipt["observation"]["success"])
        self.assertEqual([(r["tool"], r["status"]) for r in summary["tool_result_observations"]["results"]],
                         [("unknown", "error"), ("write_file", "denied"), ("write_file", "ok")])
        self.assertEqual(sum(e["type"] == "EventType.TOOL_STARTED" for e in events), 1)
        self.assertEqual(sum(e["type"] == "EventType.TOOL_FINISHED" for e in events), 3)
        self.assertEqual([row["allowed"] for row in summary["approvals"]], [False, True])

    def test_third_repeat_is_terminal_even_after_oracle_correct_output(self):
        result, receipt, events, summary, requests = self.run_case("repeat")
        self.assertEqual(result.returncode, 1)
        self.assertNotEqual(receipt["observation"]["candidate_exit_code"], 0)
        self.assertFalse(receipt["observation"]["success"])
        self.assertEqual(receipt["observation"]["failure_class"], "candidate-error")
        self.assertIn("REPEAT_LIMIT_EXCEEDED", receipt["observation"]["engine_error_types"])
        errors = [e for e in events if e["type"] == "EventType.ERROR"]
        self.assertEqual(errors, [{"type": "EventType.ERROR", "error_type": "REPEAT_LIMIT_EXCEEDED", "call_index": 3}])
        self.assertEqual(sum(e["type"] == "EventType.TOOL_STARTED" for e in events), 2)
        self.assertEqual(sum(e["type"] == "EventType.TOOL_FINISHED" for e in events), 2)
        self.assertEqual([(r["tool"], r["status"]) for r in summary["tool_result_observations"]["results"]],
                         [("write_file", "ok"), ("write_file", "ok")])
        # No fake third TOOL_FINISHED and no fourth HTTP request/dispatch; the
        # raw third SSE response is retained independently of provider telemetry.
        self.assertEqual(summary["tool_result_observations"]["event_count"], 2)
        self.assertEqual(summary["tool_result_observations"]["finished_audit_count"], 2)
        self.assertEqual(receipt["observation"]["workload"]["model_calls_started"], 3)
        before = OPTIONS.evidence_dir / "repeat/http/before-rejection-result.json"
        self.assertEqual(before.read_bytes(), RESULT.encode())
        transcript = json.loads((OPTIONS.evidence_dir / "repeat/http-transcript.json").read_text())
        self.assertEqual(transcript["records"][2]["prior_oracle_exit"], 0)
        self.assertEqual(transcript["records"][2]["prior_output_sha256"], sha(RESULT.encode()))


def main():
    global OPTIONS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--require-native", action="store_true")
    parser.add_argument("--native-python", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    OPTIONS = parser.parse_args()
    if not OPTIONS.self_test and not OPTIONS.require_native:
        parser.error("select --self-test or --require-native; native dependencies are never silently skipped")
    if OPTIONS.require_native and (OPTIONS.native_python is None or OPTIONS.evidence_dir is None):
        parser.error("native qualification requires --native-python and --evidence-dir")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProtocolControls)
    if OPTIONS.require_native:
        OPTIONS.native_python = native_python_path(OPTIONS.native_python)
        OPTIONS.evidence_dir = OPTIONS.evidence_dir.resolve()
        OPTIONS.evidence_dir.mkdir(parents=True, exist_ok=False)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(NativeLoopbackTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if OPTIONS.require_native:
        inventory = {p.relative_to(OPTIONS.evidence_dir).as_posix(): {"bytes": p.stat().st_size, "sha256": sha(p.read_bytes())}
                     for p in sorted(OPTIONS.evidence_dir.rglob("*")) if p.is_file()}
        write_json(OPTIONS.evidence_dir / "loopback-evidence.json", {
            "scope": "NATIVE_SCRIPTED_LOOPBACK_CONTRACT_NOT_MODEL_QUALITY_OR_OS_ISOLATION",
            "result": "PASS" if result.wasSuccessful() and len(CASE_RESULTS) == 2 else "NOT_PASSED",
            "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
            "skips": len(result.skipped), "native_identity": NATIVE_IDENTITY,
            "source": getattr(NativeLoopbackTests, "provenance", None), "harness_ref": HARNESS_REF,
            "cases": CASE_RESULTS, "files": inventory,
            "limits": {"turns": 4, "task_wall_seconds": 120, "output_tokens": 256,
                       "same_signature_total_attempts": 2, "request_bytes": MAX_BODY, "retained_http_records": MAX_RECORDS},
            "workflow": {key: os.environ.get(key) for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")},
            "model_attempts": 0, "real_credentials": False,
        })
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--actor":
        raise SystemExit(witness_child([sys.executable, "-B", str(ADAPTER)], sys.stdin.buffer.read(), Path(sys.argv[2])))
    raise SystemExit(main())
