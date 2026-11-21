#!/usr/bin/env bash
# Bounded public GHA only. One pinned Ollama + one pinned model + one comparison.
set -Eeuo pipefail
: "$RUNNER_TEMP"
: "$GITHUB_ACTIONS"
profile="$1"
case "$profile" in small|large) ;; *) exit 2;; esac
work="$RUNNER_TEMP/qwen-model-$profile"
mkdir -p "$work/ollama" "$work/models"
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS="$work/models"
export OLLAMA_CONTEXT_LENGTH=16384
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
curl -fL --silent --show-error --retry 3 --retry-delay 2 \
  https://github.com/ollama/ollama/releases/download/v0.34.1/ollama-linux-amd64.tar.zst \
  -o "$work/ollama.tar.zst"
echo "f361dc3992ec07e4ad429f4bb2d10d4663ba2c295f9a9a688c7d52f4ba650034  $work/ollama.tar.zst" | sha256sum -c -
zstd -dc "$work/ollama.tar.zst" | tar -xf - -C "$work/ollama"
export PATH="$work/ollama/bin:$PATH"
ollama serve >"$work/server.log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for i in $(seq 1 100); do
 if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1;then break;fi
 sleep 1
done
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null
ollama pull qwen3:1.7b
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=10) as res: rows=json.load(res)["models"]
item=next((r for r in rows if r.get("name")=="qwen3:1.7b"),None)
assert item and str(item.get("digest","")).removeprefix("sha256:").startswith("8f68893c685c"),"model digest mismatch"
print("PASS exact pinned public model")
PY
python3 qualification/qwencode_context_envelope/compare.py \
 --profile "$profile" --receipt "$RUNNER_TEMP/qwen-context-$profile-receipt.json"
