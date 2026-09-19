#!/usr/bin/env bash
set -euo pipefail

: "${SEALED_RESULT_DIR:?SEALED_RESULT_DIR is required}"

OLLAMA_VERSION="0.34.0"
OLLAMA_ARCHIVE_SHA256="cf95886728959aa09910bb34de5cca1cc5a8f68003b5597197d3f2c2d57c0804"
OPENWORKER_REVISION="5bc10d928e0b64aae74313349a3b17bd19643ae2"
QWEN_MODEL="qwen3.5:4b"
QWEN_EXPECTED_ID="2a654d98e6fb"

SPECIALIST_REPO="RichardErkhov/LLM4Binary_-_llm4decompile-1.3b-v1.5-gguf"
SPECIALIST_REVISION="d739a10877190ce7d662d0bc77f30cb99c0a9ebf"
SPECIALIST_FILE="llm4decompile-1.3b-v1.5.Q4_K_M.gguf"
SPECIALIST_SHA256="f0387b2836c971a4192afca991dac00f4fec6ff28fef67663085eb3f666b6ba6"
SPECIALIST_SIZE="873453184"
SPECIALIST_URL="https://huggingface.co/${SPECIALIST_REPO}/resolve/${SPECIALIST_REVISION}/${SPECIALIST_FILE}?download=true"

OLLAMA_ROOT="${RUNNER_TEMP:-/tmp}/llm4decompile-trial-ollama"
OLLAMA_MODELS_DIR="${RUNNER_TEMP:-/tmp}/llm4decompile-trial-models"

mkdir -p "$SEALED_RESULT_DIR" "$OLLAMA_ROOT" "$OLLAMA_MODELS_DIR"
cp plan.json "$SEALED_RESULT_DIR/plan.json"

sudo apt-get update -qq
sudo apt-get install -y -qq gcc binutils zstd >/dev/null

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

# Exact specialist acquisition.
download_started="$(date +%s)"
curl -fL --retry 1 --retry-delay 2 "$SPECIALIST_URL" -o "$SPECIALIST_FILE"
download_finished="$(date +%s)"
printf '%s  %s\n' "$SPECIALIST_SHA256" "$SPECIALIST_FILE" | sha256sum -c -
resolved_specialist_sha="$(sha256sum "$SPECIALIST_FILE" | awk '{print $1}')"
resolved_specialist_size="$(stat -c '%s' "$SPECIALIST_FILE")"
test "$resolved_specialist_size" = "$SPECIALIST_SIZE"
export SPECIALIST_SHA256="$resolved_specialist_sha"

# Stream the verified GGUF into the pinned local Ollama runtime.
SPECIALIST_DIGEST="sha256:$resolved_specialist_sha"
curl -fsS -X POST --upload-file "$SPECIALIST_FILE"   "http://$OLLAMA_HOST/api/blobs/$SPECIALIST_DIGEST"

python3 - "$SPECIALIST_DIGEST" "$SEALED_RESULT_DIR/specialist-create-request.json" <<'PY'
import json, pathlib, sys
digest=sys.argv[1]
out=pathlib.Path(sys.argv[2])
out.write_text(json.dumps({
  "model":"llm4decompile",
  "files":{"llm4decompile-1.3b-v1.5.Q4_K_M.gguf":digest},
  "parameters":{"temperature":0,"num_ctx":4096},
  "stream":False,
}, indent=2, sort_keys=True)+"\n", encoding="utf-8")
PY

curl -fsS -H 'Content-Type: application/json'   --data-binary @"$SEALED_RESULT_DIR/specialist-create-request.json"   "http://$OLLAMA_HOST/api/create"   > "$SEALED_RESULT_DIR/specialist-create-response.json"
ollama show llm4decompile >/dev/null

python3 - "$SEALED_RESULT_DIR/specialist-provenance.json" "$download_started" "$download_finished" "$resolved_specialist_sha" "$resolved_specialist_size" <<'PY'
import json, pathlib, sys
path=pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
  "schema_version":1,
  "candidate_id":"llm4decompile-1.3b-v1.5-q4_k_m",
  "packaged_repository":"RichardErkhov/LLM4Binary_-_llm4decompile-1.3b-v1.5-gguf",
  "exact_revision":"d739a10877190ce7d662d0bc77f30cb99c0a9ebf",
  "file":"llm4decompile-1.3b-v1.5.Q4_K_M.gguf",
  "sha256":sys.argv[4],
  "size_bytes":int(sys.argv[5]),
  "download_wall_seconds":int(sys.argv[3])-int(sys.argv[2]),
}, indent=2, sort_keys=True)+"\n", encoding="utf-8")
PY

export TRIAL_PLAN="$PWD/plan.json"
export RESULT_JSON="$SEALED_RESULT_DIR/result.json"

python3 run_trial.py --phase smoke

SMOKE_PASSED="$(python3 - <<'PY'
import json, os
r=json.load(open(os.environ["RESULT_JSON"],encoding="utf-8"))
print("1" if r["smoke"]["passed"] else "0")
PY
)"

if [ "$SMOKE_PASSED" != "1" ]; then
  echo "LLM4Decompile standalone smoke failed; Qwen/OpenWorker phase intentionally skipped."
else
  python3 -m pip install --disable-pip-version-check --no-input     "git+https://github.com/andrewyng/openworker.git@${OPENWORKER_REVISION}"

  ollama stop llm4decompile >/dev/null 2>&1 || true
  qwen_pull_started="$(date +%s)"
  ollama pull "$QWEN_MODEL"
  qwen_pull_finished="$(date +%s)"
  RESOLVED_MODEL_ID="$(ollama list | awk -v model="$QWEN_MODEL" '$1 == model {print $2; exit}')"
  test "$RESOLVED_MODEL_ID" = "$QWEN_EXPECTED_ID"
  export RESOLVED_MODEL_ID OPENWORKER_REVISION

  python3 - "$SEALED_RESULT_DIR/controller-provenance.json" "$qwen_pull_started" "$qwen_pull_finished" <<'PY'
import json, os, pathlib, sys
path=pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
  "schema_version":1,
  "model":"qwen3.5:4b",
  "resolved_manifest_id_prefix":os.environ["RESOLVED_MODEL_ID"],
  "openworker_revision":os.environ["OPENWORKER_REVISION"],
  "pull_wall_seconds":int(sys.argv[3])-int(sys.argv[2]),
}, indent=2, sort_keys=True)+"\n", encoding="utf-8")
PY

  python3 run_trial.py --phase integrated
fi

cp specialist_adapter.py "$SEALED_RESULT_DIR/"

python3 - <<'PY'
import hashlib, json, os
from pathlib import Path

def ident(path: Path):
    return {"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"bytes":path.stat().st_size}

out=Path(os.environ["SEALED_RESULT_DIR"])
inputs={name:ident(Path(name)) for name in ("plan.json","run.sh","run_trial.py","specialist_adapter.py")}
outputs={}
for name in (
    "plan.json","result.json","specialist-provenance.json","controller-provenance.json",
    "specialist-create-request.json","specialist-create-response.json","specialist_adapter.py"
):
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
