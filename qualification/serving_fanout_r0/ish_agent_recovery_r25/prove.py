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
MODEL = pathlib.Path(os.environ.get("ISH_MODEL", ".")).resolve()
SERVER = pathlib.Path(os.environ.get("ISH_SERVER", ".")).resolve()
SOURCE = os.environ.get("GITHUB_SHA", "")
TASKS = ("text-repair-v0", "validation-discovery-v0")
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

def arg_digest(value):
    try:
        return digest(canonical(json.loads(value) if isinstance(value,str) else value))
    except (ValueError,TypeError):
        return None

def call_projection(c):
    f = c.get("function") or {}
    return {"id":c.get("id"),"name":f.get("name"),"args_digest":arg_digest(f.get("arguments"))}

def request_projection(messages):
    rows = []
    for m in messages:
        row = {"role":m.get("role"),"content_digest":digest(canonical(m.get("content")))}
        if m.get("role")=="assistant":
            row["calls"] = [call_projection(c) for c in m.get("tool_calls") or []]
        if m.get("role")=="tool":
            row["tool_call_id"] = m.get("tool_call_id")
        rows.append(row)
    return rows

def matched_return(messages, previous):
    if not previous or not previous.get("complete"):
        return []
    calls = previous.get("response_calls",[])
    if not calls or any(not c["id"] or not c["name"] or not c["args_digest"] for c in calls):
        return []
    byid = {c["id"]:c for c in calls}
    if len(byid)!=len(calls):
        return []
    last = next((i for i in range(len(messages)-1,-1,-1) if messages[i]["role"]=="assistant"),None)
    if last is None:
        return []
    sent = messages[last].get("calls",[])
    if len(sent)!=len(calls) or {c["id"]:c for c in sent}!=byid:
        return []
    results = messages[last+1:]
    ids = [m.get("tool_call_id") for m in results]
    if any(m["role"]!="tool" for m in results) or len(ids)!=len(calls) or set(ids)!=set(byid):
        return []
    return [{"id":m["tool_call_id"],"result_digest":m["content_digest"]} for m in results]

class Witness:
    def __init__(self):
        self.calls = {}
        self.finish = []
        self.done = False
        self.first_useful = None
        self.malformed = False

    def consume(self, payload, elapsed, stream):
        for ch in payload.get("choices",[]):
            if ch.get("index",0)!=0:
                self.malformed=True
                continue
            m = ch.get("delta" if stream else "message") or {}
            if m.get("content") and self.first_useful is None:
                self.first_useful=elapsed
            for j,c in enumerate(m.get("tool_calls") or []):
                item=self.calls.setdefault(c.get("index",j),{"id":"","name":"","arguments":""})
                cid=c.get("id")
                if cid:
                    if item["id"] and item["id"]!=cid:
                        self.malformed=True
                    item["id"]=cid
                fn=c.get("function") or {}
                name,args=fn.get("name") or "",fn.get("arguments") or ""
                if not isinstance(name,str) or not isinstance(args,str):
                    self.malformed=True
                    continue
                item["name"]+=name
                item["arguments"]+=args
                if (name or args) and self.first_useful is None:
                    self.first_useful=elapsed
            if ch.get("finish_reason") is not None:
                self.finish.append(ch["finish_reason"])

    def projection(self):
        return [{"id":c["id"],"name":c["name"],"args_digest":arg_digest(c["arguments"])}
                for _,c in sorted(self.calls.items())]

    def terminal(self,stream):
        return not self.malformed and len(self.finish)==1 and bool(self.finish[0]) and (self.done or not stream)

def self_test():
    w=Witness()
    w.consume({"choices":[{"delta":{"role":"assistant"}}]},.01,True)
    require(w.first_useful is None,"role_only")
    w.consume({"choices":[{"delta":{"tool_calls":[{"index":0,"id":"a","function":{"name":"write_file","arguments":"{\"x\":"}}]}}]},.02,True)
    w.consume({"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"1}"}}]},"finish_reason":"tool_calls"}]},.03,True)
    require(w.first_useful==.02 and not w.terminal(True),"missing_done")
    w.done=True
    require(w.terminal(True),"terminal")
    prev={"complete":True,"response_calls":w.projection()}
    msgs=[{"role":"assistant","tool_calls":[{"id":"a","function":{"name":"write_file","arguments":"{\"x\":1}"}}]},
          {"role":"tool","tool_call_id":"a","content":"ok"}]
    require(len(matched_return(request_projection(msgs),prev))==1,"positive_link")
    for bad in ([msgs[0],dict(msgs[1],tool_call_id="b")],
                [dict(msgs[0],tool_calls=[{"id":"a","function":{"name":"write_file","arguments":"{\"x\":2}"}}]),msgs[1]],
                [msgs[0],msgs[1],msgs[1]],[msgs[0],msgs[1],{"role":"assistant","content":"later"}]):
        require(not matched_return(request_projection(bad),prev),"bad_link")
    require(not matched_return(request_projection(msgs),dict(prev,complete=False)),"unfinished_prior")
    empty=Witness()
    empty.done=True
    require(not empty.terminal(True),"missing_finish")
    print("PASS causal linkage and stream witness controls")

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

    def recover(self, arm, row):
        row.update(arm=arm, old_pid=self.p.pid, status="ATTEMPTED", phase="idle_check")
        t = time.monotonic()
        row["started_monotonic_s"]=t
        slots = self.rpc("/slots")
        require(isinstance(slots, list) and len(slots) == 1 and not slots[0].get("is_processing"),
                "slot_not_idle")
        if arm == "restart_restore":
            row["phase"]="snapshot_save"
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
            row["phase"]="process_stop"
            self.stop()
            row["phase"]="process_start"
            self.start()
            require(self.p.pid != row["old_pid"], "process_not_replaced")
        row["new_pid"] = self.p.pid
        if arm == "restart_restore":
            row["phase"]="snapshot_restore"
            a = time.monotonic()
            require(file_digest(snapshot) == row["snapshot_digest"], "snapshot_digest")
            restored = self.rpc("/slots/0?action=restore", {"filename": snapshot.name})
            require(restored["n_restored"] == row["saved_tokens"], "restore_count")
            row.update(restore_s=time.monotonic()-a, restored_tokens=restored["n_restored"])
        row.update(boundary_wall_s=time.monotonic()-t,status="COMPLETED",phase="complete")
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
            r["request_projection"]=request_projection(data["messages"])
            prev=self.server.events[-2] if r["request_index"]>=2 else None
            links=matched_return(r["request_projection"],prev)
            r["causal_tool_links"]=links
            if links and self.server.boundary is None:
                self.server.boundary={"request_index":r["request_index"],"causal_tool_links":links}
                r["boundary"]=True
                try:
                    self.server.native.recover(self.server.arm,self.server.boundary)
                except Exception as e:
                    b=self.server.boundary
                    b.update(status="FAILED",error_type=type(e).__name__)
                    if "started_monotonic_s" in b:
                        b["boundary_wall_s"]=time.monotonic()-b["started_monotonic_s"]
                    raise
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
            witness=Witness()
            streaming="text/event-stream" in ct
            if streaming:
                while True:
                    line = response.readline(MAX_RESPONSE+1)
                    if not line:
                        break
                    n += len(line)
                    require(n <= MAX_RESPONSE, "response_length")
                    if line.startswith(b"data:"):
                        content = line[5:].strip()
                        if content==b"[DONE]":
                            witness.done=True
                        elif content:
                            chunk=json.loads(content)
                            elapsed=time.monotonic()-start
                            if witness.done:
                                witness.malformed=True
                            witness.consume(chunk,elapsed,True)
                            if "timings" in chunk:
                                timings=chunk["timings"]
                            r.setdefault("first_event_s",elapsed)
                    self.wfile.write(line)
                    self.wfile.flush()
            else:
                payload = response.read(MAX_RESPONSE+1)
                require(len(payload) <= MAX_RESPONSE, "response_length")
                if response.status == 200:
                    body=json.loads(payload)
                    timings=body.get("timings")
                    witness.consume(body,time.monotonic()-start,False)
                self.wfile.write(payload)
                self.wfile.flush()
                n = len(payload)
            valid_counts=isinstance(timings,dict) and all(type(timings.get(k)) is int and timings[k]>=0 for k in ("cache_n","prompt_n","predicted_n"))
            r.update(native_request_s=time.monotonic()-start,response_bytes=n,
                     timings=timings if valid_counts else None,stream_done=witness.done if streaming else None,
                     finish_reasons=witness.finish,response_calls=witness.projection(),
                     first_useful_delta_s=witness.first_useful if streaming else None,
                     complete=response.status==200 and witness.terminal(streaming))
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

def run_arm(out, rep, arm, order, venv, model_digest, task):
    d = out / arm
    d.mkdir()
    native = Native(d)
    relay = None
    thread = None
    t = time.monotonic()
    row = {"rep": rep, "arm": arm, "order": order, "task":task, "status": "INFRA_FAILURE"}
    task_dir = ROOT/"qualification/tasks"/task
    task_meta = json.loads((task_dir/"task.json").read_bytes())
    try:
        native.start()
        relay = Relay(native, arm)
        thread = threading.Thread(target=relay.serve_forever, daemon=True)
        thread.start()
        packet = {"schema": "ish-agent-recovery-pilot/v2", "launch_id":
                  "%s-%s-%s-%s" % (os.environ["GITHUB_RUN_ID"],task,rep,arm),
                  "source": SOURCE, "task": task, "arm": arm,
                  "model_manifest": PIN, "model_blob": model_digest,
                  "harness": HARNESS, "server_revision": os.environ["LLAMA_REV"]}
        write(d/"packet.json", packet)
        launch_digest = digest(canonical(packet))
        meta = {"harness": {"name":"openworker", "version":"5bc10d928e0b64aae74313349a3b17bd19643ae2",
                 "artifact_ref":HARNESS, "admission_ref":ADMISSION},
                "model":{"provider":"local-openai", "id":"ish-agent", "artifact_ref":model_digest,
                         "source_manifest":"sha256:"+PIN},
                "toolset":task_meta["projected_tools"],
                "configuration":{"parallel_tool_calls":False,"max_tokens":256,"reasoning_effort":"none",
                                 "max_iterations":4,"context_length":8192,"tool_hint_mode":"none"}}
        write(d/"candidate.json",meta)
        write(d/"experiment.json",{"schema_version":2,"id":"ish-agent-recovery-r28",
                "task":{"id":task},"claim_type":"framework-proving",
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
               "--substrate-profile-id","ish-public-cpu-r28","--substrate-profile-commit",SOURCE,
               "--timeout-override","240","--experiment",str(d/"experiment.json"),
               "--launch-id",packet["launch_id"],"--launch-packet-digest",launch_digest,
               "--snapshot-dir",str(d/"snapshot")]
        for k in candidate_env:
            cmd += ["--pass-env",k]
        cmd += [str(task_dir),str(d/"candidate.json"),str(d/"receipt.json"),
                "--",str(venv/"bin/python"),str(ROOT/"qualification/adapters/openworker_projected.py")]
        result = subprocess.run(cmd,env=env,capture_output=True,timeout=300)
        row["runner_exit"] = result.returncode
        row["runner_stderr_digest"] = digest(result.stderr)
        require((d/"receipt.json").exists(),"missing_task_receipt")
        raw = (d/"receipt.json").read_bytes()
        receipt = json.loads(raw)
        obs = receipt["observation"]
        require(receipt["task"]["id"]==task and receipt["task"]["source_commit"]==SOURCE,
                "task_source_binding")
        require(receipt["launch"]=={"launch_id":packet["launch_id"],"packet_digest":launch_digest},
                "launch_binding")
        require(type(obs["success"]) is bool and result.returncode==(0 if obs["success"] else 1),
                "canonical_acceptance")
        if obs["success"]:
            require(obs["verifier_exit_code"]==obs["candidate_exit_code"]==0 and not obs["timed_out"],
                    "canonical_verifier")
            check=subprocess.run([sys.executable,str(task_dir/"verify.py"),str(d/"snapshot")],capture_output=True,timeout=15)
            require(check.returncode==0,"accepted_snapshot_mismatch")
            manifest=json.loads((d/"snapshot/snapshot_manifest.json").read_bytes())
            for name in task_meta["allowed_write_paths"]:
                payload=d/"snapshot"/name
                m=manifest["files"][name]
                require(payload.is_file() and m["sha256"]==file_digest(payload) and m["size_bytes"]==payload.stat().st_size,"snapshot_digest")
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
            b=relay.boundary
            row["boundary_status"]=b["status"] if b else ("UNMATCHED_TOOL_RESULT" if any(q.get("tool_result_present") for q in relay.events) else "NOT_REACHED")
            row["native_reuse_status"]="UNKNOWN"
            if b and b["status"]=="COMPLETED":
                q=relay.events[b["request_index"]-1]
                if q.get("complete") and q.get("timings") is not None:
                    row["native_reuse_status"]="REUSED" if q["timings"]["cache_n"]>0 else "ZERO_REUSE"
            row["qualification_ready"]=row.get("accepted") is True and row["boundary_status"]=="COMPLETED" and bool(relay.events) and all(q.get("complete") for q in relay.events) and row["native_reuse_status"]==("ZERO_REUSE" if arm=="restart_cold" else "REUSED")
        native.stop()
        row.update(epochs=native.epochs,total_wall_s=time.monotonic()-t)
        write(d/"result.json",row)
        return row

def main():
    if sys.argv[1]=="--self-test":
        self_test()
        return
    rep = int(sys.argv[1])
    out = pathlib.Path(sys.argv[2]).resolve()
    venv = pathlib.Path(sys.argv[3]).resolve()
    task=sys.argv[4]
    require(task in TASKS,"task")
    out.mkdir()
    model_digest = file_digest(MODEL)
    require(model_digest == os.environ["ISH_MODEL_BLOB_DIGEST"],"model_identity")
    require(0 <= rep < 3,"rep")
    # Three Latin-square rotations screen for order effects; not a population estimate.
    order = ARMS[rep:] + ARMS[:rep]
    rows = [run_arm(out,rep,a,i,venv,model_digest,task) for i,a in enumerate(order)]
    write(out/"summary.json",{"scope":"FRAMEWORK_PROVING_ONLY","source":SOURCE,"rep":rep,"task":task,
          "planned_arms":list(order),"rows":rows,"model_manifest":"sha256:"+PIN,
          "model_blob":model_digest,"promotion_authorized":False,
          "limitations":"strict causal and terminal witnesses; semantic acceptance distinct; no production or hardware acceptance"})
    # Fail only missing/invalid infrastructure receipts; semantic failure and
    # non-reached boundaries are observed results, not silently dropped.
    require(all(r["status"]=="OBSERVED" for r in rows),"incomplete_receipts")

if __name__ == "__main__":
    main()
