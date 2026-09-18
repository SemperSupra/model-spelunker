#!/usr/bin/env bash
set -euo pipefail

: "${SEALED_RESULT_DIR:?SEALED_RESULT_DIR is required}"

OLLAMA_VERSION="0.34.0"
OLLAMA_ARCHIVE_SHA256="cf95886728959aa09910bb34de5cca1cc5a8f68003b5597197d3f2c2d57c0804"
OPENWORKER_REVISION="5bc10d928e0b64aae74313349a3b17bd19643ae2"
QWEN_MODEL="qwen3.5:4b"
QWEN_EXPECTED_ID="2a654d98e6fb"
RTLCODER_REVISION="fc60b2440a782487654f573bbaed2c8a39647e8e"
RTLCODER_FILE="ggml-model-q4_0.gguf"
RTLCODER_SHA256="860753548c58bc298db10e0173e73b73f89724ce848b6be1491cd01eb7131a54"
RTLCODER_URL="https://huggingface.co/ishorn5/RTLCoder-v1.1-gguf-4bit/resolve/${RTLCODER_REVISION}/${RTLCODER_FILE}?download=true"

OLLAMA_ROOT="${RUNNER_TEMP:-/tmp}/rtlcoder-trial-ollama"
OLLAMA_MODELS_DIR="${RUNNER_TEMP:-/tmp}/rtlcoder-trial-models"

mkdir -p "$SEALED_RESULT_DIR" "$OLLAMA_ROOT" "$OLLAMA_MODELS_DIR"
cp plan.json "$SEALED_RESULT_DIR/plan.json"

sudo apt-get update -qq
sudo apt-get install -y -qq iverilog zstd >/dev/null

curl -fsSL   "https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}/ollama-linux-amd64.tar.zst"   -o "$OLLAMA_ROOT/ollama-linux-amd64.tar.zst"
printf '%s  %s\n' "$OLLAMA_ARCHIVE_SHA256" "$OLLAMA_ROOT/ollama-linux-amd64.tar.zst" | sha256sum -c -
tar --zstd -xf "$OLLAMA_ROOT/ollama-linux-amd64.tar.zst" -C "$OLLAMA_ROOT"

export PATH="$OLLAMA_ROOT/bin:$PATH"
export OLLAMA_HOST="127.0.0.1:11434"
export OLLAMA_MODELS="$OLLAMA_MODELS_DIR"
export OLLAMA_NOHISTORY=1
export OLLAMA_CONTEXT_LENGTH=4096
export OLLAMA_MAX_LOADED_MODELS=1

ollama serve >"$SEALED_RESULT_DIR/ollama.log" 2>&1 &
OLLAMA_PID=$!
trap 'kill "$OLLAMA_PID" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 60); do
  if curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null

# Cheap request-shape canary before the multi-GB specialist transfer.
PREFLIGHT_FILE="$OLLAMA_ROOT/create-preflight.bin"
printf 'not-a-model\n' > "$PREFLIGHT_FILE"
PREFLIGHT_SHA="$(sha256sum "$PREFLIGHT_FILE" | awk '{print $1}')"
PREFLIGHT_DIGEST="sha256:$PREFLIGHT_SHA"
curl -fsS -X POST --data-binary @"$PREFLIGHT_FILE" \
  "http://$OLLAMA_HOST/api/blobs/$PREFLIGHT_DIGEST"
python3 - "$PREFLIGHT_DIGEST" "$SEALED_RESULT_DIR/create-preflight-request.json" <<'PY'
import json, pathlib, sys
digest=sys.argv[1]
path=pathlib.Path(sys.argv[2])
path.write_text(json.dumps({
  "model":"rtlcoder-preflight",
  "files":{"not-a-model.gguf":digest},
  "parameters":{"temperature":0,"num_ctx":4096},
  "stream":False,
}, indent=2, sort_keys=True)+"\n", encoding="utf-8")
PY
preflight_status="$(curl -sS -o "$SEALED_RESULT_DIR/create-preflight-response.json" -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  --data-binary @"$SEALED_RESULT_DIR/create-preflight-request.json" \
  "http://$OLLAMA_HOST/api/create")"
if grep -qi 'invalid model name' "$SEALED_RESULT_DIR/create-preflight-response.json"; then
  echo "Ollama create request-shape preflight rejected model name" >&2
  exit 3
fi
printf '%s\n' "$preflight_status" > "$SEALED_RESULT_DIR/create-preflight-status.txt"

# Cheap streaming-body canary: prove the blob upload form without an external model transfer.
STREAM_PREFLIGHT_FILE="$OLLAMA_ROOT/blob-stream-preflight.bin"
truncate -s 33554432 "$STREAM_PREFLIGHT_FILE"
STREAM_PREFLIGHT_SHA="$(sha256sum "$STREAM_PREFLIGHT_FILE" | awk '{print $1}')"
STREAM_PREFLIGHT_DIGEST="sha256:$STREAM_PREFLIGHT_SHA"
curl -fsS -X POST --upload-file "$STREAM_PREFLIGHT_FILE" \
  "http://$OLLAMA_HOST/api/blobs/$STREAM_PREFLIGHT_DIGEST"
rm -f "$STREAM_PREFLIGHT_FILE"

# Phase 1: exact specialist acquisition and standalone deterministic smoke.
download_started="$(date +%s)"
curl -fL --retry 1 --retry-delay 2 "$RTLCODER_URL" -o "$RTLCODER_FILE"
download_finished="$(date +%s)"
printf '%s  %s\n' "$RTLCODER_SHA256" "$RTLCODER_FILE" | sha256sum -c -
RESOLVED_RTLCODER_SHA256="$(sha256sum "$RTLCODER_FILE" | awk '{print $1}')"
export RTLCODER_SHA256="$RESOLVED_RTLCODER_SHA256"

RTLCODER_DIGEST="sha256:$RESOLVED_RTLCODER_SHA256"
curl -fsS -X POST --upload-file "$RTLCODER_FILE" \
  "http://$OLLAMA_HOST/api/blobs/$RTLCODER_DIGEST"
python3 - "$RTLCODER_DIGEST" "$SEALED_RESULT_DIR/rtlcoder-create-request.json" <<'PY'
import json, pathlib, sys
digest=sys.argv[1]
path=pathlib.Path(sys.argv[2])
path.write_text(json.dumps({
  "model":"rtlcoder",
  "files":{"ggml-model-q4_0.gguf":digest},
  "parameters":{"temperature":0,"num_ctx":4096},
  "stream":False,
}, indent=2, sort_keys=True)+"\n", encoding="utf-8")
PY
curl -fsS -H 'Content-Type: application/json' \
  --data-binary @"$SEALED_RESULT_DIR/rtlcoder-create-request.json" \
  "http://$OLLAMA_HOST/api/create" \
  > "$SEALED_RESULT_DIR/rtlcoder-create-response.json"
ollama show rtlcoder >/dev/null

export TRIAL_PLAN="$PWD/plan.json"
export RESULT_JSON="$SEALED_RESULT_DIR/result.json"
python3 run_trial.py --phase smoke

python3 - "$SEALED_RESULT_DIR/specialist-provenance.json" "$download_started" "$download_finished" <<'PY'
import json, os, pathlib, sys
out=pathlib.Path(sys.argv[1])
record={
  "schema_version":1,
  "candidate_id":"rtlcoder-v1.1-gguf-q4_0",
  "ollama_model":"rtlcoder",
  "source_revision":"fc60b2440a782487654f573bbaed2c8a39647e8e",
  "file":"ggml-model-q4_0.gguf",
  "sha256":os.environ["RTLCODER_SHA256"],
  "size_bytes":pathlib.Path("ggml-model-q4_0.gguf").stat().st_size,
  "download_wall_seconds":int(sys.argv[3])-int(sys.argv[2]),
}
out.write_text(json.dumps(record,indent=2,sort_keys=True)+"\n",encoding="utf-8")
PY

SMOKE_PASSED="$(python3 - <<'PY'
import json, os
r=json.load(open(os.environ["RESULT_JSON"],encoding="utf-8"))
print("1" if r["smoke"]["passed"] else "0")
PY
)"

if [ "$SMOKE_PASSED" != "1" ]; then
  echo "RTLCoder standalone smoke failed; integrated controller phase intentionally skipped."
else
  # Phase 2 is unlocked only by the independent specialist smoke oracle.
  python3 -m pip install --disable-pip-version-check --no-input     "git+https://github.com/andrewyng/openworker.git@${OPENWORKER_REVISION}"

  ollama stop rtlcoder >/dev/null 2>&1 || true
  qwen_pull_started="$(date +%s)"
  ollama pull "$QWEN_MODEL"
  qwen_pull_finished="$(date +%s)"
  RESOLVED_MODEL_ID="$(ollama list | awk -v model="$QWEN_MODEL" '$1 == model {print $2; exit}')"
  test -n "$RESOLVED_MODEL_ID"
  test "$RESOLVED_MODEL_ID" = "$QWEN_EXPECTED_ID"
  export RESOLVED_MODEL_ID OPENWORKER_REVISION

  python3 - "$SEALED_RESULT_DIR/controller-provenance.json" "$qwen_pull_started" "$qwen_pull_finished" <<'PY'
import json, os, pathlib, sys
record={
  "schema_version":1,
  "model":"qwen3.5:4b",
  "resolved_manifest_id_prefix":os.environ["RESOLVED_MODEL_ID"],
  "openworker_revision":os.environ["OPENWORKER_REVISION"],
  "pull_wall_seconds":int(sys.argv[3])-int(sys.argv[2]),
}
pathlib.Path(sys.argv[1]).write_text(json.dumps(record,indent=2,sort_keys=True)+"\n",encoding="utf-8")
PY

  python3 run_trial.py --phase integrated
fi

cp specialist_adapter.py "$SEALED_RESULT_DIR/"

python3 - <<'PY'
import hashlib, json, os
from pathlib import Path

def ident(path: Path):
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}

out=Path(os.environ["SEALED_RESULT_DIR"])
inputs={}
for name in ("plan.json","run.sh","run_trial.py","specialist_adapter.py"):
    p=Path(name)
    inputs[name]=ident(p)
outputs={}
for name in ("plan.json","result.json","specialist-provenance.json","controller-provenance.json","create-preflight-request.json","create-preflight-response.json","create-preflight-status.txt","rtlcoder-create-request.json","rtlcoder-create-response.json"):
    p=out/name
    if p.is_file():
        outputs[name]=ident(p)
receipt={
  "schema_version":1,
  "record_type":"execution-receipt",
  "inputs":inputs,
  "outputs":outputs,
}
(out/"execution-receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
PY
