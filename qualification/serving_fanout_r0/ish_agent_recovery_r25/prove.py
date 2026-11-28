#!/usr/bin/env python3
"""Bounded public fixture: canonical OpenWorker task across one native server restart.

No new agent, task verifier, scheduler, or production gateway. The loopback
relay exists only to place a known inference boundary in the existing actor.
All arms, including semantic failures and absent boundaries, remain in evidence.
"""
import hashlib
import http.client
import http.server
import itertools
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[3]
ARMS = ("resident", "restart_cold", "restart_restore")
MAX_RESPONSE = 8 * 1024 * 1024
PIN = "8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
MODEL = pathlib.Path(os.environ["ISH_MODEL"]).resolve()
SERVER = pathlib.Path(os.environ["ISH_SERVER"]).resolve()
SOURCE = os.environ["GITHUB_SHA"]
PORT = 18081
HARNESS = "ghcr.io/sempersupra/model-spelunker-harness-openworker@sha256:e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83"
ADMISSION = "github:SemperSupra/model-spelunker@4f939c4beccb7652b851c4a228d78d804b0e95c7:qualification/harness-artifacts/openworker-5bc10d928e0b-linux-x64.admission-v2.json"

def digest(b):
    return "sha256:" + hashlib.sha256(b).hexdigest()

def canonical(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()

def file_digest(p):
    with p.open("rb") as f:
        return "sha256:" + hashlib.file_digest(f, "sha256").hexdigest()

def write(p, o):
    p.write_text(json.dumps(o, indent=2, sort_keys=True) + "\n")

def require(ok, reason):
    if not ok:
        raise ValueError(reason)

class Native:
    def __init__(self, directory):
        self.directory = directory
        self.slots = directory / "slots"
        self.slots.mkdir()
        self.p = None
        self.epochs = []

    def rpc(self, path, payload=None):
        data = None if payload is None else canonical(payload)
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)

    def start(self):
        t = time.monotonic()
        with (self.directory / "native.log").open("ab") as log:
            self.p = subprocess.Popen([str(SERVER), "-m", str(MODEL), "--alias", "ish-agent",
                 "-c", "8192", "-np", "1", "-t", "4", "-ngl", "0", "--jinja",
                 "--cache-ram", "0", "--no-cache-idle-slots",
                 "--host", "127.0.0.1", "--port", str(PORT), "--slot-save-path", str(self.slots)],
                 stdout=log, stderr=log)
        for _ in range(240):
            require(self.p.poll() is None, "native_process_exited")
            try:
                self.rpc("/health")
                self.epochs.append({"pid": self.p.pid, "startup_s": time.monotonic()-t})
                return
            except OSError:
                time.sleep(.25)
        raise RuntimeError("native_readiness_timeout")

    def stop(self):
        if self.p is not None:
            if self.p.poll() is None:
                self.p.terminate()
                try:
                    self.p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.p.kill()
                    self.p.wait()
            self.p = None

    def recover(self, arm):
        row = {"arm": arm, "old_pid": self.p.pid}
        t = time.monotonic()
        slots = self.rpc("/slots")
        require(isinstance(slots, list) and len(slots) == 1 and not slots[0].get("is_processing"),
                "slot_not_idle")
        if arm == "restart_restore":
            a = time.monotonic()
            saved = self.rpc("/slots/0?action=save", {"filename": "boundary.partial"})
            stage = self.slots / "boundary.partial"
            with stage.open("rb") as f:
                os.fsync(f.fileno())
            n = stage.stat().st_size
            require(n == saved["n_written"] and saved["n_saved"] > 0, "save_count")
            h = file_digest(stage)
            snapshot = self.slots / "boundary.bin"
            os.replace(stage, snapshot)
            fd = os.open(self.slots, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            row.update(save_s=time.monotonic()-a, saved_tokens=saved["n_saved"],
                       snapshot_bytes=n, snapshot_digest=h)
        if arm != "resident":
            self.stop()
            self.start()
            require(self.p.pid != row["old_pid"], "process_not_replaced")
        row["new_pid"] = self.p.pid
        if arm == "restart_restore":
            a = time.monotonic()
            require(file_digest(snapshot) == row["snapshot_digest"], "snapshot_digest")
            restored = self.rpc("/slots/0?action=restore", {"filename": snapshot.name})
            require(restored["n_restored"] == row["saved_tokens"], "restore_count")
            row.update(restore_s=time.monotonic()-a, restored_tokens=restored["n_restored"])
        row["boundary_wall_s"] = time.monotonic()-t
        return row

class Relay(http.server.HTTPServer):
    allow_reuse_address = True
    def __init__(self, native, arm):
        self.native = native
        self.arm = arm
        self.events = []
        self.boundary = None
        super().__init__(("127.0.0.1", 0), Handler)

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *_):
        pass

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        r = {"request_index": len(self.server.events)+1, "complete": False}
        self.server.events.append(r)
        connection = None
        sent = False
        try:
            length = int(self.headers.get("Content-Length", "0"))
            require(0 < length <= 1024*1024, "request_length")
            data = json.loads(self.rfile.read(length))
            require(data.get("model") == "ish-agent" and isinstance(data.get("messages"), list),
                    "request_model_or_messages")
            r.update(request_digest=digest(canonical(data)),
                     tool_result_present=any(m.get("role") == "tool" for m in data["messages"]),
                     message_count=len(data["messages"]))
            # Intervene at the first observed return from a real tool, never on
            # an arbitrary timer or an in-flight generation.
            if r["request_index"] >= 2 and r["tool_result_present"] and self.server.boundary is None:
                self.server.boundary = self.server.native.recover(self.server.arm)
                r["boundary"] = True
            data.update(id_slot=0, cache_prompt=True, seed=42, temperature=0)
            if not isinstance(data.get("chat_template_kwargs"), dict):
                data["chat_template_kwargs"] = {}
            data["chat_template_kwargs"]["enable_thinking"] = False
            r["forwarded_request_digest"] = digest(canonical(data))
            start = time.monotonic()
            connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=180)
            connection.request("POST", self.path, body=canonical(data),
                               headers={"Content-Type": "application/json", "Connection": "close"})
            response = connection.getresponse()
            r["status"] = response.status
            ct = response.getheader("Content-Type") or "application/json"
            self.send_response(response.status)
            self.send_header("Content-Type", ct)
            self.send_header("Connection", "close")
            self.end_headers()
            sent = True
            n = 0
            timings = None
            if "text/event-stream" in ct:
                while True:
                    line = response.readline(MAX_RESPONSE+1)
                    if not line:
                        break
                    n += len(line)
                    require(n <= MAX_RESPONSE, "response_length")
                    if line.startswith(b"data:"):
                        content = line[5:].strip()
                        if content and content != b"[DONE]":
                            chunk = json.loads(content)
                            if "timings" in chunk:
                                timings = chunk["timings"]
                            if "first_event_s" not in r:
                                r["first_event_s"] = time.monotonic()-start
                    self.wfile.write(line)
                    self.wfile.flush()
            else:
                payload = response.read(MAX_RESPONSE+1)
                require(len(payload) <= MAX_RESPONSE, "response_length")
                if response.status == 200:
                    timings = json.loads(payload).get("timings")
                self.wfile.write(payload)
                self.wfile.flush()
                n = len(payload)
            r.update(native_request_s=time.monotonic()-start, response_bytes=n,
                     timings=timings, complete=response.status==200)
        except Exception as e:
            r["error"] = type(e).__name__ + ":" + str(e)[:160]
            if not sent:
                self.send_error(502, "fixture boundary failure")
        finally:
            if connection is not None:
                connection.close()
            self.close_connection = True

    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        body = canonical(self.server.native.rpc("/v1/models"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def run_arm(out, rep, arm, order, venv, model_digest):
    d = out / arm
    d.mkdir()
    native = Native(d)
    relay = None
    thread = None
    t = time.monotonic()
    row = {"rep": rep, "arm": arm, "order": order, "status": "INFRA_FAILURE"}
    try:
        native.start()
        relay = Relay(native, arm)
        thread = threading.Thread(target=relay.serve_forever, daemon=True)
        thread.start()
        packet = {"schema": "ish-agent-recovery-pilot/v1", "launch_id":
                  "%s-%s-%s" % (os.environ["GITHUB_RUN_ID"],rep,arm),
                  "source": SOURCE, "task": "text-repair-v0", "arm": arm,
                  "model_manifest": PIN, "model_blob": model_digest,
                  "harness": HARNESS, "server_revision": os.environ["LLAMA_REV"]}
        write(d/"packet.json", packet)
        launch_digest = digest(canonical(packet))
        meta = {"harness": {"name":"openworker", "version":"5bc10d928e0b64aae74313349a3b17bd19643ae2",
                 "artifact_ref":HARNESS, "admission_ref":ADMISSION},
                "model":{"provider":"local-openai", "id":"ish-agent", "artifact_ref":model_digest,
                         "source_manifest":"sha256:"+PIN},
                "toolset":["read_file","write_file"],
                "configuration":{"parallel_tool_calls":False,"max_tokens":256,"reasoning_effort":"none",
                                 "max_iterations":4,"context_length":8192,"tool_hint_mode":"none"}}
        write(d/"candidate.json",meta)
        write(d/"experiment.json",{"schema_version":2,"id":"ish-agent-recovery-r25",
                "task":{"id":"text-repair-v0"},"claim_type":"framework-proving",
                "experimental_role":"control","design_block":rep,
                "primary_responses":["accepted","native_recovery","full_wall"]})
        env = {k:v for k,v in os.environ.items() if k.lower() not in
               ("http_proxy","https_proxy","all_proxy")}
        candidate_env = {"MODEL_SPELUNKER_MODEL":"local-openai:ish-agent",
                         "MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL":"http://127.0.0.1:%d/v1"%relay.server_port,
                         "MODEL_SPELUNKER_MAX_ITERATIONS":"4","MODEL_SPELUNKER_MAX_TOKENS":"256",
                         "MODEL_SPELUNKER_REASONING_EFFORT":"none","MODEL_SPELUNKER_TOOL_HINT_MODE":"none"}
        env.update(candidate_env)
        cmd = [sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",SOURCE,
               "--substrate-profile-id","ish-public-cpu-r25","--substrate-profile-commit",SOURCE,
               "--timeout-override","240","--experiment",str(d/"experiment.json"),
               "--launch-id",packet["launch_id"],"--launch-packet-digest",launch_digest,
               "--snapshot-dir",str(d/"snapshot")]
        for k in candidate_env:
            cmd += ["--pass-env",k]
        cmd += [str(ROOT/"qualification/tasks/text-repair-v0"),str(d/"candidate.json"),str(d/"receipt.json"),
                "--",str(venv/"bin/python"),str(ROOT/"qualification/adapters/openworker_projected.py")]
        result = subprocess.run(cmd,env=env,capture_output=True,timeout=300)
        row["runner_exit"] = result.returncode
        row["runner_stderr_digest"] = digest(result.stderr)
        require((d/"receipt.json").exists(),"missing_task_receipt")
        raw = (d/"receipt.json").read_bytes()
        receipt = json.loads(raw)
        obs = receipt["observation"]
        require(receipt["task"]["id"]=="text-repair-v0" and receipt["task"]["source_commit"]==SOURCE,
                "task_source_binding")
        require(receipt["launch"]=={"launch_id":packet["launch_id"],"packet_digest":launch_digest},
                "launch_binding")
        require(type(obs["success"]) is bool and result.returncode==(0 if obs["success"] else 1),
                "canonical_acceptance")
        if obs["success"]:
            require(obs["verifier_exit_code"]==obs["candidate_exit_code"]==0 and not obs["timed_out"],
                    "canonical_verifier")
            require((d/"snapshot/value.txt").read_bytes()==b"READY\n","accepted_snapshot_mismatch")
        row.update(run_id=receipt["run_id"],receipt_sha256=digest(raw),
                   accepted=obs["success"],task_wall_s=obs["wall_seconds"],
                   termination_class=obs["termination_class"],status="OBSERVED")
    except Exception as e:
        row["error"] = type(e).__name__ + ":" + str(e)[:160]
    finally:
        if relay is not None:
            relay.shutdown()
            relay.server_close()
            thread.join(timeout=5)
            row.update(requests=relay.events,boundary=relay.boundary)
        native.stop()
        row.update(epochs=native.epochs,total_wall_s=time.monotonic()-t)
        write(d/"result.json",row)
        return row

def main():
    rep = int(sys.argv[1])
    out = pathlib.Path(sys.argv[2]).resolve()
    venv = pathlib.Path(sys.argv[3]).resolve()
    out.mkdir()
    model_digest = file_digest(MODEL)
    require(model_digest == os.environ["ISH_MODEL_BLOB_DIGEST"],"model_identity")
    require(0 <= rep < 3,"rep")
    # Three Latin-square rotations screen for order effects; not a population estimate.
    order = ARMS[rep:] + ARMS[:rep]
    rows = [run_arm(out,rep,a,i,venv,model_digest) for i,a in enumerate(order)]
    write(out/"summary.json",{"scope":"FRAMEWORK_PROVING_ONLY","source":SOURCE,"rep":rep,
          "planned_arms":list(order),"rows":rows,"model_manifest":"sha256:"+PIN,
          "model_blob":model_digest,"promotion_authorized":False,
          "limitations":"one public task, observed tool boundary required; no production or hardware acceptance"})
    # Fail only missing/invalid infrastructure receipts; semantic failure and
    # non-reached boundaries are observed results, not silently dropped.
    require(all(r["status"]=="OBSERVED" for r in rows),"incomplete_receipts")

if __name__ == "__main__":
    main()
