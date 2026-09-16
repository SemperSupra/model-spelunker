#!/usr/bin/env bash
set -euo pipefail

: "${SEALED_RESULT_DIR:?SEALED_RESULT_DIR is required by Agent Dispatch sealed execution}"

QUALIFICATION_JSON="$PWD/qualification.json"
RESULT_JSON="$SEALED_RESULT_DIR/result.json"
OLLAMA_VERSION="0.34.0"
OLLAMA_ARCHIVE_SHA256="cf95886728959aa09910bb34de5cca1cc5a8f68003b5597197d3f2c2d57c0804"
OLLAMA_ROOT="${RUNNER_TEMP:-/tmp}/persona-ollama"
OLLAMA_MODELS_DIR="${RUNNER_TEMP:-/tmp}/persona-ollama-models"

MODEL="$(python3 - <<'PY'
import json
p=json.load(open("qualification.json", encoding="utf-8"))
models={x["controller"]["model"] for x in p["personas"]}
versions={x["controller"]["runtime_version"] for x in p["personas"]}
if len(models) != 1 or len(versions) != 1:
    raise SystemExit("canary requires one shared controller model/runtime")
if next(iter(versions)) != "0.34.0":
    raise SystemExit("qualification plan/runtime version does not match pinned run.sh")
print(next(iter(models)))
PY
)"

sudo apt-get update -qq
sudo apt-get install -y -qq iverilog zstd >/dev/null

python3 -m pip install --disable-pip-version-check --no-input \
  "smolagents[litellm]==1.26.0"

mkdir -p "$OLLAMA_ROOT" "$OLLAMA_MODELS_DIR"
curl -fsSL \
  "https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}/ollama-linux-amd64.tar.zst" \
  -o "$OLLAMA_ROOT/ollama-linux-amd64.tar.zst"
printf '%s  %s\n' "$OLLAMA_ARCHIVE_SHA256" "$OLLAMA_ROOT/ollama-linux-amd64.tar.zst" \
  | sha256sum -c -
tar --zstd -xf "$OLLAMA_ROOT/ollama-linux-amd64.tar.zst" -C "$OLLAMA_ROOT"

export PATH="$OLLAMA_ROOT/bin:$PATH"
export OLLAMA_HOST="127.0.0.1:11434"
export OLLAMA_MODELS="$OLLAMA_MODELS_DIR"
export OLLAMA_NOHISTORY=1

ollama serve >"$OLLAMA_ROOT/ollama.log" 2>&1 &
OLLAMA_PID=$!
trap 'kill "$OLLAMA_PID" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 60); do
  if curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null

ollama pull "$MODEL"
RESOLVED_MODEL_ID="$(ollama list | awk -v model="$MODEL" '$1 == model {print $2; exit}')"
test -n "$RESOLVED_MODEL_ID"
RESOLVED_OLLAMA_VERSION="$(ollama --version | awk '{print $NF}')"

export QUALIFICATION_JSON
export RESULT_JSON
export RESOLVED_MODEL_ID
export RESOLVED_OLLAMA_VERSION

set +e
python3 run_reproduction.py
task_rc=$?
set -e

cp qualification.json "$SEALED_RESULT_DIR/qualification.json"
export TASK_RC="$task_rc"

python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path


def identity(path: Path) -> dict[str, object]:
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


out = Path(os.environ["SEALED_RESULT_DIR"])
inputs = {
    name: identity(Path(name))
    for name in ("qualification.json", "run.sh", "run_reproduction.py")
}
outputs = {}
for name in ("qualification.json", "result.json"):
    path = out / name
    if path.is_file():
        outputs[name] = identity(path)

receipt = {
    "schema_version": 1,
    "record_type": "execution-receipt",
    "task_exit_code": int(os.environ["TASK_RC"]),
    "inputs": inputs,
    "outputs": outputs,
}
(out / "execution-receipt.json").write_text(
    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

exit "$task_rc"
