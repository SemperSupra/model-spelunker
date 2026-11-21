#!/usr/bin/env bash
# Disposable PUBLIC GHA runner only. Zero sovereign endpoint/secret access.
set -Eeuo pipefail
: "$RUNNER_TEMP"
: "$GITHUB_ACTIONS"
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS="$RUNNER_TEMP/qwen-public-ollama-models"
export OLLAMA_CONTEXT_LENGTH=8192
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
mkdir -p "$RUNNER_TEMP/qwen-public-ollama/bin" "$OLLAMA_MODELS"
curl -fL --silent --show-error --retry 3 --retry-delay 2 \
  https://github.com/ollama/ollama/releases/download/v0.34.1/ollama-linux-amd64.tar.zst \
  -o "$RUNNER_TEMP/qwen-public-ollama.tar.zst"
echo "f361dc3992ec07e4ad429f4bb2d10d4663ba2c295f9a9a688c7d52f4ba650034  $RUNNER_TEMP/qwen-public-ollama.tar.zst" | sha256sum -c -
zstd -dc "$RUNNER_TEMP/qwen-public-ollama.tar.zst" | tar -xf - -C "$RUNNER_TEMP/qwen-public-ollama"
export PATH="$RUNNER_TEMP/qwen-public-ollama/bin:$PATH"
ollama serve > "$RUNNER_TEMP/qwen-public-ollama.log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for n in $(seq 1 80); do
  if curl -fsS http://127.0.0.1:11434/api/tags > /dev/null; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null
ollama pull qwen3:1.7b
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=10) as req:
    models=json.load(req)["models"]
target=next((m for m in models if m.get("name")=="qwen3:1.7b"),None)
assert target and str(target.get("digest","")).removeprefix("sha256:").startswith("8f68893c685c"), "model digest mismatch"
print("PASS pinned Qwen3 1.7B Ollama model")
PY
python3 qualification/qwencode_model_diagnostics/probe.py \
  --receipt "$RUNNER_TEMP/qwen-direct-ollama-receipt.json"
