#!/usr/bin/env bash
# Source-neutral model/tool fixture. Disposable PUBLIC GitHub Actions runner only.
set -euo pipefail
: "$RUNNER_TEMP"
: "$GITHUB_ACTIONS"
export OLLAMA_VERSION=0.34.1
export OLLAMA_SHA256=f361dc3992ec07e4ad429f4bb2d10d4663ba2c295f9a9a688c7d52f4ba650034
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS="$RUNNER_TEMP/qwen-smoke-models"
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_CONTEXT_LENGTH=8192
export OLLAMA_API_KEY=ollama
export MODEL_TAG=qwen3:1.7b
export MODEL_DIGEST_PREFIX=8f68893c685c
mkdir -p "$RUNNER_TEMP/ollama" "$OLLAMA_MODELS"
curl -fL --silent --show-error --retry 3 --retry-delay 2 \
  "https://github.com/ollama/ollama/releases/download/v$OLLAMA_VERSION/ollama-linux-amd64.tar.zst" \
  -o "$RUNNER_TEMP/ollama.tar.zst"
echo "$OLLAMA_SHA256  $RUNNER_TEMP/ollama.tar.zst" | sha256sum -c -
zstd -dc "$RUNNER_TEMP/ollama.tar.zst" | tar -xf - -C "$RUNNER_TEMP/ollama"
export PATH="$RUNNER_TEMP/ollama/bin:$PATH"
nohup ollama serve >"$RUNNER_TEMP/qwen-ollama.log" 2>&1 &
for i in $(seq 1 60); do
  if curl -fsS "http://$OLLAMA_HOST/api/tags" >/dev/null; then break; fi
  sleep 1
done
curl -fsS "http://$OLLAMA_HOST/api/tags" >/dev/null
ollama pull "$MODEL_TAG"
python3 - <<'PY'
import json,os,urllib.request
with urllib.request.urlopen('http://'+os.environ['OLLAMA_HOST']+'/api/tags',timeout=10) as r:
    models=json.load(r)['models']
target=next((m for m in models if m.get('name')==os.environ['MODEL_TAG']),None)
assert target is not None,'model unavailable'
assert target['digest'].removeprefix('sha256:').startswith(os.environ['MODEL_DIGEST_PREFIX']),'model digest mismatch'
print('PASS pinned public local model')
PY
python3 qualification/qwencode_public/kit.py fetch --platform linux-x64 --archive "$RUNNER_TEMP/qwen-code-linux-x64.tar.gz"
python3 qualification/qwencode_public/kit.py smoke --platform linux-x64 \
  --archive "$RUNNER_TEMP/qwen-code-linux-x64.tar.gz" --out "$RUNNER_TEMP/qwen-native"
export HOME="$RUNNER_TEMP/qwen-home"
mkdir -p "$HOME/.qwen" "$RUNNER_TEMP/qwen-agent-task"
python3 - <<'PY'
import json,os,pathlib
home=pathlib.Path(os.environ['HOME'])
data={
  'security':{'auth':{'selectedType':'openai'}},
  'model':{'name':'qwen3:1.7b'},
  'modelProviders':{'openai':[{
     'id':'qwen3:1.7b','envKey':'OLLAMA_API_KEY',
     'baseUrl':'http://127.0.0.1:11434/v1',
     'generationConfig':{'timeout':180000,'maxRetries':1,'contextWindowSize':8192,
         'samplingParams':{'temperature':0,'max_tokens':512}}
  }]},
  'memory':{'enableManagedAutoMemory':False,'enableManagedAutoDream':False,
      'enableTeamMemory':False,'enableTeamMemorySync':False},
  'privacy':{'usageStatisticsEnabled':False},
  'tools':{'approvalMode':'yolo'},
  'mcpServers':{}
}
(home/'.qwen'/'settings.json').write_text(json.dumps(data))
PY
printf 'VALUE=17\n' >"$RUNNER_TEMP/qwen-agent-task/fixture.txt"
cd "$RUNNER_TEMP/qwen-agent-task"
set +e
timeout 180 "$RUNNER_TEMP/qwen-native/qwen-code/bin/qwen" \
  -p 'Use read_file to open fixture.txt; report its exact contents, including VALUE=17.' \
  --model 'qwen3:1.7b' --approval-mode yolo --max-session-turns 4 \
  --max-tool-calls 8 --max-wall-time 3m --output-format json \
  >"$RUNNER_TEMP/qwen-agent-result.json" 2>"$RUNNER_TEMP/qwen-agent-stderr.txt"
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  echo "QWEN_EXIT=$rc"; cat "$RUNNER_TEMP/qwen-agent-stderr.txt" >&2
  exit "$rc"
fi
python3 - <<'PY'
import json,os,pathlib
p=pathlib.Path(os.environ['RUNNER_TEMP'],'qwen-agent-result.json')
events=json.loads(p.read_text())
assert isinstance(events,list) and events,'no transcript'
final=next((x for x in reversed(events) if x.get('type')=='result'),{})
assert final and not final.get('is_error',True),'no terminal success'
result=str(final.get('result',''))
assert 'VALUE=17' in result,'independent fixture oracle not passed'
had_tool='read_file' in p.read_text()
receipt={'schema':'qwencode-public-agent-smoke/v1',
 'model':'qwen3:1.7b','endpoint_class':'local-runner-ollama',
 'fixture_oracle':'PASS','tool_name_evidenced':had_tool,
 'cross_trust_data':'NOT_USED','site_acceptance':'NOT_TESTED'}
pathlib.Path(os.environ['RUNNER_TEMP'],'qwen-agent-receipt.json').write_text(json.dumps(receipt,sort_keys=True)+'\n')
print(json.dumps(receipt,sort_keys=True))
PY
