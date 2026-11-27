#!/usr/bin/env bash
# Public disposable GitHub Actions only: actual model-backed installed Qwen embodiment.
set -Eeuo pipefail
: "$RUNNER_TEMP"; : "$GITHUB_ACTIONS"
test "$GITHUB_ACTIONS" = true
export CI=true QWEN_TELEMETRY_ENABLED=false PYTHONDONTWRITEBYTECODE=1
export OLLAMA_HOST=127.0.0.1:11434 OLLAMA_CONTEXT_LENGTH=32768
export OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_MODELS="$RUNNER_TEMP/qwen-r18-models"
root="$RUNNER_TEMP/qwen-r18-live"
cell="$RUNNER_TEMP/qwen-r18-installed"
mkdir -p "$root/ollama" "$root/task" "$OLLAMA_MODELS"
ollama_pid=
cleanup() {
  if [[ -n "$ollama_pid" ]]; then kill "$ollama_pid" 2>/dev/null || true; wait "$ollama_pid" 2>/dev/null || true; fi
  if [[ -d "$cell" ]]; then python3 qualification/agent_embodiment/qwen_embody.py remove --root "$cell" || true; fi
}
trap cleanup EXIT
curl -fL --silent --show-error --retry 3 --retry-delay 2 https://github.com/ollama/ollama/releases/download/v0.34.1/ollama-linux-amd64.tar.zst -o "$root/ollama.tar.zst"
echo "f361dc3992ec07e4ad429f4bb2d10d4663ba2c295f9a9a688c7d52f4ba650034  $root/ollama.tar.zst" | sha256sum -c -
zstd -dc "$root/ollama.tar.zst" | tar -xf - -C "$root/ollama"
export PATH="$root/ollama/bin:$PATH"
ollama serve >"$root/ollama.log" 2>&1 &
ollama_pid=$!
for i in $(seq 1 80); do curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null
ollama pull qwen3:1.7b
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=10) as response: models=json.load(response)["models"]
match=next((x for x in models if x.get("name")=="qwen3:1.7b"),None)
assert match and str(match.get("digest","")).removeprefix("sha256:").startswith("8f68893c685c")
print("PASS pinned native model census")
PY
python3 qualification/qwencode_public/kit.py fetch --platform linux-x64 --archive "$root/qwen-code-linux-x64.tar.gz"
python3 qualification/agent_embodiment/qwen_embody.py stage --root "$cell" --archive "$root/qwen-code-linux-x64.tar.gz"
python3 qualification/agent_embodiment/qwen_embody.py verify --root "$cell"
python3 - <<'PY'
import os,secrets,json
from pathlib import Path
from qualification.agent_embodiment.classify_reliability_trial import fixture_fingerprint
root=Path(os.environ["RUNNER_TEMP"])/"qwen-r18-live"
cell=Path(os.environ["RUNNER_TEMP"])/"qwen-r18-installed"
target="a.txt" if secrets.randbelow(2)==0 else "b.txt"
(root/"task/index.txt").write_text("TARGET="+target+"\n")
(root/"task/a.txt").write_text("VALUE="+secrets.token_hex(16)+"\n")
(root/"task/b.txt").write_text("VALUE="+secrets.token_hex(16)+"\n")
(root/"fixture-before.sha256").write_text(fixture_fingerprint(root/"task"))
cfg=json.loads((cell/"home/.qwen/settings.json").read_text())
assert cfg["modelProviders"]["openai"][0]["baseUrl"]=="http://127.0.0.1:11434/v1"
(cell/"home/.qwen/lean-system.md").write_text(
"You are a limited public-synthetic file reader. Work only in the disposable "
"current task directory. First read index.txt, then read the TARGET file. Do not "
"guess file contents, use shell commands, search external files, write data "
"or describe unperformed actions. The session is headless and only the "
"read_file tool is available. After reading index.txt and its TARGET file, "
"return only the VALUE line from the selected TARGET file. Do not return index text.\n")
PY
export HOME="$cell/home" OLLAMA_API_KEY=ollama
export QWEN_SYSTEM_MD="$HOME/.qwen/lean-system.md"
export QWEN_WRITE_SYSTEM_MD=0 QWEN_SYSTEM_IDENTITY_MD=0
set +e
(
 cd "$root/task"
 timeout 150 "$cell/native/qwen-code/bin/qwen" --prompt \
 'Use read_file on index.txt. Its TARGET names a second file; read that file using read_file and output only its VALUE. Do not guess.' \
 --model qwen3:1.7b --core-tools read_file --approval-mode default \
 --max-session-turns 4 --max-tool-calls 4 --max-wall-time 140s --output-format json \
 >"$root/cli.stdout" 2>"$root/cli.stderr"
)
rc=$?
set -e
export R18_EXIT="$rc"
python3 - <<'PY'
import os,sys,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/"qualification/agent_embodiment"))
from final_oracle import verify_selected,classify_final
from lineage_oracle import lineage_verdict
from settings_drift import audit as audit_settings
from classify_reliability_trial import fixture_fingerprint,execution_identity
root=Path(os.environ["RUNNER_TEMP"])/"qwen-r18-live"
cell=Path(os.environ["RUNNER_TEMP"])/"qwen-r18-installed"
fixture_before=(root/"fixture-before.sha256").read_text()
fixture_after=fixture_fingerprint(root/"task")
if fixture_before!=fixture_after:raise ValueError("synthetic fixture changed during execution")
execution=execution_identity(int(os.environ.get("R25_TRIAL_INDEX","0")))
target=(root/"task/index.txt").read_text().split("=",1)[1].strip()
assert target in ("a.txt","b.txt")
expected=(root/"task"/target).read_text().strip()
decoy=(root/"task"/("b.txt" if target=="a.txt" else "a.txt")).read_text().strip()
stdout_bytes=(root/"cli.stdout").read_bytes()
stdout=stdout_bytes.decode("utf-8",errors="replace")
lineage=lineage_verdict(stdout,root/"task",target)
drift=audit_settings(cell/"home/.qwen/settings.json")
final=classify_final(stdout,expected,decoy)
good=int(os.environ["R18_EXIT"])==0 and lineage=="PASS" and verify_selected(stdout,expected,decoy) and drift["byte_identical"]
# Diagnose settings effects but keep task correctness independent of configuration integrity.
receipt={
 "schema":"agent-embodiment-native-use/v1","framework":"QWEN_CODE_0_28_3",
 "runtime":"OLLAMA_0_34_1_QWEN3_1P7B_32K","source_class":"PUBLIC_SYNTHETIC",
 "installed_settings_sha256":hashlib.sha256((cell/"home/.qwen/settings.json").read_bytes()).hexdigest(),
 "post_run_settings_drift":drift,
 "execution":execution,"fixture_before_sha256":fixture_before,"fixture_after_sha256":fixture_after,
 "model_stdout_sha256":hashlib.sha256(stdout_bytes).hexdigest(),
 "cli_exit":int(os.environ["R18_EXIT"]),"tool_lineage_class":lineage,
 "final_answer_class":final,"independent_hidden_oracle":"PASS" if verify_selected(stdout,expected,decoy) else "FAIL",
 "post_run_profile_integrity":"PASS" if drift["byte_identical"] else "FAIL",
 "model_inference":"ACTUAL","operational_admission":"NOT_GRANTED",
 "verdict":"PASS" if good else "FAIL"}
(root/"receipt.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
print(json.dumps(receipt,sort_keys=True))
if not good:raise SystemExit(1)
PY
