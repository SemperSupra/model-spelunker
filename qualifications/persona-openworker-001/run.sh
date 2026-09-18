#!/usr/bin/env bash
set -euo pipefail

: "${SEALED_RESULT_DIR:?SEALED_RESULT_DIR is required}"

QUALIFICATION_JSON="$PWD/qualification.json"
RESULT_JSON="$SEALED_RESULT_DIR/result.json"
OLLAMA_VERSION="0.34.0"
OLLAMA_ARCHIVE_SHA256="cf95886728959aa09910bb34de5cca1cc5a8f68003b5597197d3f2c2d57c0804"
OPENWORKER_REVISION="5bc10d928e0b64aae74313349a3b17bd19643ae2"
OLLAMA_ROOT="${RUNNER_TEMP:-/tmp}/persona-openworker-ollama"
OLLAMA_MODELS_DIR="${RUNNER_TEMP:-/tmp}/persona-openworker-models"
FIXTURE_SPEC="../../fixtures/rtl-fifo4-v1/spec.md"
FIXTURE_TB="../../fixtures/rtl-fifo4-v1/tb.sv"
DRAFT_SOURCE="failed-specialist-draft.v"
DRAFT_SHA256="2feb5811b4a324699cf32321eeecff3807ec5f15d8d2b6d1e81d10ab9a4de0b2"
DRAFT_BYTES="856"

MODEL="$(python3 - <<'PY'
import json
p=json.load(open("qualification.json", encoding="utf-8"))
models={x["controller"]["model"] for x in p["personas"]}
versions={x["controller"]["runtime_version"] for x in p["personas"]}
revs={x["framework"]["revision"] for x in p["personas"]}
if len(models) != 1 or len(versions) != 1 or len(revs) != 1:
    raise SystemExit("portability canary requires one shared controller/runtime/framework revision")
if next(iter(versions)) != "0.34.0":
    raise SystemExit("qualification plan/runtime version does not match pinned run.sh")
if next(iter(revs)) != "5bc10d928e0b64aae74313349a3b17bd19643ae2":
    raise SystemExit("qualification plan/OpenWorker revision does not match pinned run.sh")
print(next(iter(models)))
PY
)"

mkdir -p "$SEALED_RESULT_DIR"
sudo apt-get update -qq
sudo apt-get install -y -qq iverilog zstd >/dev/null

# Reconfirm the exact frozen RTLCoder draft is the known-bad FIFO artifact before model compute.
resolved_draft_sha="$(sha256sum "$DRAFT_SOURCE" | awk '{print $1}')"
resolved_draft_bytes="$(stat -c '%s' "$DRAFT_SOURCE")"
test "$resolved_draft_sha" = "$DRAFT_SHA256"
test "$resolved_draft_bytes" = "$DRAFT_BYTES"

DRAFT_CHECK_DIR="$(mktemp -d)"
cp "$DRAFT_SOURCE" "$DRAFT_CHECK_DIR/solution.v"
cp "$FIXTURE_TB" "$DRAFT_CHECK_DIR/tb.sv"
iverilog -g2012 -s tb -o "$DRAFT_CHECK_DIR/sim" "$DRAFT_CHECK_DIR/solution.v" "$DRAFT_CHECK_DIR/tb.sv"
vvp "$DRAFT_CHECK_DIR/sim" > "$SEALED_RESULT_DIR/draft-precheck.out" 2>&1 || true
draft_failures="$(grep -c '^FAIL ' "$SEALED_RESULT_DIR/draft-precheck.out" || true)"
test "$draft_failures" = "254"
if grep -qx 'PASS' "$SEALED_RESULT_DIR/draft-precheck.out"; then
  echo "frozen draft unexpectedly passed FIFO oracle" >&2
  exit 3
fi
python3 - "$SEALED_RESULT_DIR/draft-precheck.json" "$resolved_draft_sha" "$resolved_draft_bytes" "$draft_failures" <<'PY'
import json, pathlib, sys
path=pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
  "schema_version":1,
  "record_type":"frozen-draft-precheck",
  "sha256":sys.argv[2],
  "bytes":int(sys.argv[3]),
  "oracle_failures":int(sys.argv[4]),
  "expected_oracle_failures":254,
  "passed_precondition":int(sys.argv[4]) == 254,
}, indent=2, sort_keys=True)+"\n", encoding="utf-8")
PY
rm -rf "$DRAFT_CHECK_DIR"

python3 -m pip install --disable-pip-version-check --no-input \
  "git+https://github.com/andrewyng/openworker.git@${OPENWORKER_REVISION}"

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
export OLLAMA_CONTEXT_LENGTH=4096

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

pull_started="$(date +%s)"
ollama pull "$MODEL"
pull_finished="$(date +%s)"
RESOLVED_MODEL_ID="$(ollama list | awk -v model="$MODEL" '$1 == model {print $2; exit}')"
test -n "$RESOLVED_MODEL_ID"
RESOLVED_OLLAMA_VERSION="$(ollama --version | awk '{print $NF}')"

MANIFEST_PATH="$(find "$OLLAMA_MODELS_DIR/manifests" -type f -print -quit)"
test -n "$MANIFEST_PATH"
cp "$MANIFEST_PATH" "$SEALED_RESULT_DIR/ollama-model-manifest.json"

python3 - "$MANIFEST_PATH" "$SEALED_RESULT_DIR/model-provenance.json" "$MODEL" "$RESOLVED_MODEL_ID" "$pull_started" "$pull_finished" <<'PY'
import hashlib, json, pathlib, sys
manifest_path=pathlib.Path(sys.argv[1])
out=pathlib.Path(sys.argv[2])
model=sys.argv[3]
resolved=sys.argv[4]
pull_started=int(sys.argv[5])
pull_finished=int(sys.argv[6])
raw=manifest_path.read_bytes()
manifest=json.loads(raw)
layers=[]
for layer in manifest.get("layers", []):
    layers.append({
        "digest": layer.get("digest"),
        "size": layer.get("size"),
        "mediaType": layer.get("mediaType"),
    })
cfg=manifest.get("config") or {}
record={
    "schema_version": 1,
    "model": model,
    "ollama_resolved_id_prefix": resolved,
    "manifest_sha256": hashlib.sha256(raw).hexdigest(),
    "manifest_bytes": len(raw),
    "config": {
        "digest": cfg.get("digest"),
        "size": cfg.get("size"),
        "mediaType": cfg.get("mediaType"),
    },
    "layers": layers,
    "pull_wall_seconds": pull_finished-pull_started,
}
out.write_text(json.dumps(record, indent=2, sort_keys=True)+"\n", encoding="utf-8")
PY

export QUALIFICATION_JSON RESULT_JSON RESOLVED_MODEL_ID RESOLVED_OLLAMA_VERSION OPENWORKER_REVISION

set +e
python3 run_reproduction.py
task_rc=$?
set -e

cp qualification.json "$SEALED_RESULT_DIR/qualification.json"
cp "$FIXTURE_SPEC" "$SEALED_RESULT_DIR/rtl-fifo4-spec.md"
cp "$FIXTURE_TB" "$SEALED_RESULT_DIR/rtl-fifo4-tb.sv"
cp "$DRAFT_SOURCE" "$SEALED_RESULT_DIR/failed-specialist-draft.v"
export TASK_RC="$task_rc"

python3 - <<'PY'
import hashlib, json, os
from pathlib import Path

def identity(path: Path):
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}

out=Path(os.environ["SEALED_RESULT_DIR"])
input_paths={
    "qualification.json": Path("qualification.json"),
    "run.sh": Path("run.sh"),
    "run_reproduction.py": Path("run_reproduction.py"),
    "rtl-fifo4-spec.md": Path("../../fixtures/rtl-fifo4-v1/spec.md"),
    "rtl-fifo4-tb.sv": Path("../../fixtures/rtl-fifo4-v1/tb.sv"),
    "failed-specialist-draft.v": Path("failed-specialist-draft.v"),
}
inputs={name: identity(path) for name, path in input_paths.items()}
outputs={}
for name in ("qualification.json","result.json","model-provenance.json","ollama-model-manifest.json","rtl-fifo4-spec.md","rtl-fifo4-tb.sv","failed-specialist-draft.v","draft-precheck.json","draft-precheck.out"):
    path=out/name
    if path.is_file():
        outputs[name]=identity(path)
receipt={
    "schema_version":1,
    "record_type":"execution-receipt",
    "task_exit_code":int(os.environ["TASK_RC"]),
    "inputs":inputs,
    "outputs":outputs,
}
(out/"execution-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n", encoding="utf-8")
PY

exit "$task_rc"
