#!/usr/bin/env bash
# ACTUAL Qwen CLI -> FAKE public loopback provider -> real read_file -> fixture oracle.
# This does NOT qualify inference or any sovereign model/provider.
set -Eeuo pipefail
: "$RUNNER_TEMP"
: "$GITHUB_ACTIONS"
: "$GITHUB_WORKSPACE"
export CI=true
export PYTHONDONTWRITEBYTECODE=1
export QWEN_TELEMETRY_ENABLED=false
work="$RUNNER_TEMP/qwen-public-wire"
mkdir -p "$work/home/.qwen" "$work/task"
python3 - <<'PY'
import os,pathlib,secrets
path=pathlib.Path(os.environ["RUNNER_TEMP"],"qwen-public-wire","task","fixture.txt")
path.write_text("VALUE="+secrets.token_hex(12)+"\n")
PY
server_pid=
cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
python3 -u qualification/qwencode_wire/mock_provider.py \
  --file "$work/task/fixture.txt" --state "$work/mock-events.json" \
  --port-file "$work/port" >"$work/mock-stdout.txt" 2>"$work/mock-stderr.txt" &
server_pid=$!
for i in $(seq 1 100); do
  [[ -s "$work/port" ]] && break
  sleep 0.1
done
test -s "$work/port"
export PUBLIC_WIRE_PORT
PUBLIC_WIRE_PORT=$(cat "$work/port")
python3 - <<'PY'
import os,urllib.request,json
port=int(os.environ["PUBLIC_WIRE_PORT"])
assert 1<=port<=65535
with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",timeout=3) as res:
    assert json.load(res)["status"]=="OK"
print("PASS fake provider loopback health")
PY
python3 qualification/qwencode_public/kit.py fetch \
  --platform linux-x64 --archive "$work/qwen-code-linux-x64.tar.gz"
python3 qualification/qwencode_public/kit.py smoke \
  --platform linux-x64 --archive "$work/qwen-code-linux-x64.tar.gz" \
  --out "$work/native"
export HOME="$work/home"
export PUBLIC_WIRE_KEY="public-synthetic"
python3 - <<'PY'
import os,json,pathlib
root=pathlib.Path(os.environ["HOME"],".qwen")
port=int(os.environ["PUBLIC_WIRE_PORT"])
settings={
    "security":{"auth":{"selectedType":"openai"}},
    "model":{"name":"qwen-public-wire"},
    "modelProviders":{"openai":[{
      "id":"qwen-public-wire","name":"Public synthetic wire oracle",
      "envKey":"PUBLIC_WIRE_KEY",
      "baseUrl":f"http://127.0.0.1:{port}/v1",
      "generationConfig":{"timeout":25000,"maxRetries":0,
                          "contextWindowSize":32768,
                          "samplingParams":{"temperature":0}}
    }]},
    "memory":{"enableManagedAutoMemory":False,"enableManagedAutoDream":False,
              "enableStructuredRecall":False,"enableTeamMemory":False,
              "enableTeamMemorySync":False},
    "experimental":{"agentTeam":False},
    "privacy":{"usageStatisticsEnabled":False},
    "tools":{"approvalMode":"yolo"},
    "mcpServers":{}
}
(root/"settings.json").write_text(json.dumps(settings))
PY
set +e
(
  cd "$work/task"
  timeout 95 "$work/native/qwen-code/bin/qwen" \
    -p 'Use read_file to open fixture.txt. Return exactly the value stored there; no guessing.' \
    --model qwen-public-wire --approval-mode yolo \
    --max-session-turns 4 --max-tool-calls 8 --max-wall-time 90s \
    --output-format json \
    > "$work/cli-result.json" 2> "$work/cli-stderr.txt"
)
rc=$?
set -e
export QWEN_WIRE_RC="$rc"
python3 - <<'PY'
import json,os,pathlib
root=pathlib.Path(os.environ["RUNNER_TEMP"],"qwen-public-wire")
expected=(root/"task/fixture.txt").read_text().strip()
state=json.loads((root/"mock-events.json").read_text())
events=state["events"]
phases=[x["phase"] for x in events]
result=(root/"cli-result.json").read_text(errors="replace")
passed=int(os.environ["QWEN_WIRE_RC"])==0 and \
    "read-file-call-sent" in phases and "tool-result-seen" in phases and \
    expected in result
out={
  "schema":"qwen-public-wire-smoke/v1",
  "result":"PASS" if passed else "FAIL",
  "source_class":"PUBLIC_SYNTHETIC",
  "provider":"FAKE_LOCAL_LOOPBACK",
  "model_inference":"NOT_TESTED",
  "native_qwen":"EXECUTED",
  "tool_call_requested":"read-file-call-sent" in phases,
  "tool_result_observed":"tool-result-seen" in phases,
  "hidden_fixture_oracle":"PASS" if expected in result else "FAIL",
  "qwen_exit":int(os.environ["QWEN_WIRE_RC"]),
  "actual_ollama_openrouter_sovereign":"NOT_TESTED",
  "guest_os_boot":"NOT_TESTED"
}
(root/"receipt.json").write_text(json.dumps(out,indent=2)+"\n")
print(json.dumps(out,sort_keys=True))
if not passed:
  print("Qwen stdout last 1600 characters:",result[-1600:].replace(expected,"<REDACTED>"))
  print("Qwen stderr last 1600 characters:",(root/"cli-stderr.txt").read_text(errors="replace")[-1600:])
  raise SystemExit(1)
PY
