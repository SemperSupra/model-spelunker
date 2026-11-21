#!/usr/bin/env bash
# Actual public-only pinned Ollama / model, one disposable hosted CPU runner.
set -Eeuo pipefail
: "$RUNNER_TEMP"
: "$GITHUB_ACTIONS"
case "$1" in r7-12kb|r7-19kb|r7-25kb) profile="$1";; *) exit 2;; esac
root="$RUNNER_TEMP/qwen-r7-$profile"
mkdir -p "$root/ollama" "$root/models"
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS="$root/models"
export OLLAMA_CONTEXT_LENGTH=16384
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
curl -fL --silent --show-error --retry 3 --retry-delay 2 \
  https://github.com/ollama/ollama/releases/download/v0.34.1/ollama-linux-amd64.tar.zst \
  -o "$root/ollama.tar.zst"
echo "f361dc3992ec07e4ad429f4bb2d10d4663ba2c295f9a9a688c7d52f4ba650034  $root/ollama.tar.zst" | sha256sum -c -
zstd -dc "$root/ollama.tar.zst" | tar -xf - -C "$root/ollama"
export PATH="$root/ollama/bin:$PATH"
ollama serve >"$root/ollama.log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true;wait "$pid" 2>/dev/null || true' EXIT
for i in $(seq 1 100);do
 if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1;then break;fi
 sleep 1
done
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null
ollama pull qwen3:1.7b
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=10) as v:m=json.load(v)["models"]
x=next((i for i in m if i.get("name")=="qwen3:1.7b"),None)
assert x and str(x.get("digest","")).removeprefix("sha256:").startswith("8f68893c685c"),"model pin mismatch"
print("PASS pinned public Ollama/Qwen3:1.7b")
PY
python3 qualification/qwencode_envelope_r7/probe.py \
 --profile "$profile" --output "$RUNNER_TEMP/qwen-r7-$profile.json"
