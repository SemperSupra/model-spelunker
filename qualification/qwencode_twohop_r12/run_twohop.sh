#!/usr/bin/env bash
# Public disposable GHA ONLY; Qwen CLI + actual local CPU Ollama behind loopback.
set -Eeuo pipefail
: "$RUNNER_TEMP"
: "$GITHUB_ACTIONS"
export CI=true
export QWEN_TELEMETRY_ENABLED=false
export PYTHONDONTWRITEBYTECODE=1
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS="$RUNNER_TEMP/qwen-harness-models"
export OLLAMA_CONTEXT_LENGTH=32768
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
root="$RUNNER_TEMP/qwen-r12-twohop"
mkdir -p "$root/ollama" "$root/home/.qwen" "$root/task" "$OLLAMA_MODELS"
ollama_pid=
proxy_pid=
cleanup() {
  if [[ -n "$proxy_pid" ]]; then kill "$proxy_pid" 2>/dev/null || true; wait "$proxy_pid" 2>/dev/null || true; fi
  if [[ -n "$ollama_pid" ]]; then kill "$ollama_pid" 2>/dev/null || true; wait "$ollama_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT
curl -fL --silent --show-error --retry 3 --retry-delay 2 \
  https://github.com/ollama/ollama/releases/download/v0.34.1/ollama-linux-amd64.tar.zst \
  -o "$root/ollama.tar.zst"
echo "f361dc3992ec07e4ad429f4bb2d10d4663ba2c295f9a9a688c7d52f4ba650034  $root/ollama.tar.zst" | sha256sum -c -
zstd -dc "$root/ollama.tar.zst" | tar -xf - -C "$root/ollama"
export PATH="$root/ollama/bin:$PATH"
ollama serve >"$root/ollama.log" 2>&1 &
ollama_pid=$!
for i in $(seq 1 80); do
  curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null
ollama pull qwen3:1.7b
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=10) as v:
    rows=json.load(v)["models"]
match=next((r for r in rows if r.get("name")=="qwen3:1.7b"),None)
assert match and str(match.get("digest","")).removeprefix("sha256:").startswith("8f68893c685c")
print("PASS pinned public local Qwen3 model")
PY
python3 -u qualification/qwencode_twohop_r12/wire_proxy.py \
  --port-file "$root/proxy-port" --state "$root/proxy-metadata.json" --mode baseline \
  >"$root/proxy.stdout" 2>"$root/proxy.stderr" &
proxy_pid=$!
for i in $(seq 1 100); do
  [[ -s "$root/proxy-port" ]] && break
  sleep 0.1
done
test -s "$root/proxy-port"
export QWEN_PROXY_PORT
QWEN_PROXY_PORT=$(cat "$root/proxy-port")
python3 - <<'PY'
import json,os,urllib.request
with urllib.request.urlopen("http://127.0.0.1:"+os.environ["QWEN_PROXY_PORT"]+"/health",timeout=5) as v:
    assert json.load(v)["status"]=="OK"
PY
python3 qualification/qwencode_public/kit.py fetch \
  --platform linux-x64 --archive "$root/qwen-code-linux-x64.tar.gz"
python3 qualification/qwencode_public/kit.py smoke \
  --platform linux-x64 --archive "$root/qwen-code-linux-x64.tar.gz" \
  --out "$root/native"
python3 - <<'PY'
import pathlib,os,secrets,json
p=pathlib.Path(os.environ["RUNNER_TEMP"],"qwen-r12-twohop")
target="a.txt" if secrets.randbelow(2)==0 else "b.txt"
(p/"task/index.txt").write_text("TARGET="+target+"\n")
(p/"task/a.txt").write_text("VALUE="+secrets.token_hex(16)+"\n")
(p/"task/b.txt").write_text("VALUE="+secrets.token_hex(16)+"\n")
settings={
  "security":{"auth":{"selectedType":"openai"}},
  "model":{"name":"qwen3:1.7b"},
  "modelProviders":{"openai":[{
     "id":"qwen3:1.7b","envKey":"OLLAMA_API_KEY",
     "baseUrl":"http://127.0.0.1:"+os.environ["QWEN_PROXY_PORT"]+"/v1",
     "generationConfig":{"timeout":140000,"maxRetries":0,
                         "contextWindowSize":32768,
                         "samplingParams":{"temperature":0,
                                           "max_tokens":256,
                                           "reasoning_effort":"none"}}
  }]},
  "tools":{"core":["read_file"],"eager":["read_file"],"toolSearch":{"enabled":False}},
  "memory":{"enableManagedAutoMemory":False,"enableManagedAutoDream":False,
            "enableTeamMemory":False,"enableTeamMemorySync":False},
  "experimental":{"agentTeam":False},
  "mcpServers":{},
  "privacy":{"usageStatisticsEnabled":False}
}
(p/"home/.qwen/settings.json").write_text(json.dumps(settings))
(p/"home/.qwen/lean-system.md").write_text(
    "You are a limited public-synthetic file reader. Work only in the disposable "
    "current task directory. First read index.txt, then read the TARGET file. Do not "
    "guess file contents, use shell commands, search external files, write data "
    "or describe unperformed actions. The session is headless and only the "
    "read_file tool is available. Return exactly the file text after it is read.\n")

PY
export HOME="$root/home"
export OLLAMA_API_KEY=ollama
export QWEN_SYSTEM_MD="$root/home/.qwen/lean-system.md"
export QWEN_WRITE_SYSTEM_MD=0
export QWEN_SYSTEM_IDENTITY_MD=0

set +e
(
  cd "$root/task"
  timeout 150 "$root/native/qwen-code/bin/qwen" \
    --prompt 'Use read_file on index.txt. Its TARGET names a second file; read that file using read_file and output only its VALUE. Do not guess.' \
    --model qwen3:1.7b --core-tools read_file --approval-mode default --max-session-turns 4 \
    --max-tool-calls 4 --max-wall-time 140s --output-format json \
    >"$root/cli.stdout" 2>"$root/cli.stderr"
)
rc=$?
set -e
export QWEN_LEAN_RC="$rc"
python3 - <<'PY'
import json,os,pathlib,sys
sys.path.insert(0,str(pathlib.Path.cwd()/"qualification/qwencode_twohop_r12"))
from final_oracle import verify_selected,classify_final
p=pathlib.Path(os.environ["RUNNER_TEMP"],"qwen-r12-twohop")
target=(p/"task/index.txt").read_text().strip().split("=",1)[1]
assert target in ("a.txt","b.txt")
expected=(p/"task"/target).read_text().strip()
decoy=(p/"task"/("b.txt" if target=="a.txt" else "a.txt")).read_text().strip()
stdout=(p/"cli.stdout").read_text(errors="replace")
metadata=json.loads((p/"proxy-metadata.json").read_text()) if (p/"proxy-metadata.json").is_file() else {"events":[]}
events=metadata.get("events",[])
completed=[v for v in events if v.get("phase")=="upstream-request" and v.get("result")!="IN_PROGRESS"]
valid=int(os.environ["QWEN_LEAN_RC"])==0 and verify_selected(stdout,expected,decoy) and sum(
   v.get("sse_tool_delta_events",0) for v in completed)>=2 and bool(completed) and all(
   v.get("requested_output_budget",0)>=256 and "read_file" in v.get("tool_names",[]) for v in completed)
status="PASS" if valid else "FAIL"
receipt={
 "schema":"qwen-r12-two-hop-selection/v1",
 "verdict":status,
 "core_allowlist":["read_file"],
 "bridge_disabled":True,
 "approval_mode":"default",
 "full_system_override":"QWEN_SYSTEM_MD_RUNNER_OWNED",
 "model_inference":"ACTUAL_PINNED_OLLAMA_QWEN3_1P7B",
 "qwen_exit":int(os.environ["QWEN_LEAN_RC"]),
 "hidden_fixture_oracle":"PASS" if verify_selected(stdout,expected,decoy) else "FAIL",
 "final_answer_source":"QWEN_CLI_JSON_RESULT_FRAME_ONLY",
 "final_answer_class":classify_final(stdout,expected,decoy),
 "two_hop_tool_delta_min":sum(v.get("sse_tool_delta_events",0) for v in completed),
 "request_seen":bool(completed),
 "request_count":len(completed),
 "upstream_request_bytes":[e.get("request_bytes") for e in completed],
 "system_content_chars":[e.get("system_content_chars") for e in completed],
 "tools_advertised":[e.get("tools_count") for e in completed],
 "tool_names":[e.get("tool_names") for e in completed],
 "response_elapsed_seconds":[e.get("response_elapsed_seconds") for e in completed],
 "first_sse_event_seconds":[e.get("first_sse_event_seconds") for e in completed],
 "tool_deltas":[e.get("sse_tool_delta_events") for e in completed],
 "wire_output_budgets":[e.get("requested_output_budget") for e in completed],
 "finish_reasons":[e.get("finish_reasons") for e in completed],
 "private_host_or_model":"NOT_USED",
 "hyperv_guest":"NOT_TESTED",
 "source_class":"PUBLIC_SYNTHETIC"
}
(p/"receipt.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
print(json.dumps(receipt,sort_keys=True))
if not valid:
    errors=(p/"cli.stderr").read_text(errors="replace")
    print("Qwen stderr category:","NO_RESPONSE_TEXT" if "Model stream ended with empty response text" in errors else "OTHER_OR_UNKNOWN")
    raise SystemExit(1)
PY
