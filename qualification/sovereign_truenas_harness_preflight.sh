#!/usr/bin/env bash
set -euo pipefail

# Zero-inference preflight for admitted Model Spelunker harness artifacts.
# Intended to run on the sovereign TrueNAS Linux/x86_64 node.
# This script does not call any model endpoint and does not persist credentials.

OPENWORKER_REF='ghcr.io/sempersupra/model-spelunker-harness-openworker@sha256:e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83'
GOOSE_REF='ghcr.io/sempersupra/model-spelunker-harness-goose@sha256:e4202698e3442086b2aa69de8d9a155740d2ddcb234905cc6e7108ed54f2b636'
CODEX_REF='ghcr.io/sempersupra/model-spelunker-harness-codex-exec@sha256:56e23dcbd8c96143d8a20c0ecf8babbcbe1619c78bb9b8fe195dd5a40bc32338'

OPENWORKER_SHA='5bc10d928e0b64aae74313349a3b17bd19643ae2'
GOOSE_SHA='2090ad1c65ddb39497601a936a9fe17d66254bfe'
CODEX_SHA='6b9826e3aa83b1a5947db50f4332cb9c65f1b340'
GOOSE_VERSION='1.51.0'
CODEX_VERSION='0.154.0'
CODEX_NATIVE_SHA='da4bc5c13a97a4a21999919bde2a9e2c943904a7bd444893d5ac8fc35c0b51f3'
CODEX_PATCH_SHA='237e3b219738b5199a92236a2dfa0a8fd3ac25dad03586084d6616535a194e15'
GOOSE_NATIVE_SHA='f117d4f40bedc3e5371e04355729f1ba27066a5552be691cd22296e6294e2699'

for cmd in docker python3; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "required command unavailable: $cmd" >&2
    exit 2
  }
done

arch="$(uname -m)"
if [ "$arch" != "x86_64" ]; then
  echo "unsupported preflight architecture: $arch" >&2
  exit 2
fi

root="$(mktemp -d -t model-spelunker-sovereign-harness-preflight.XXXXXX)"
docker_config="$root/docker-config"
mkdir -p "$docker_config"
export DOCKER_CONFIG="$docker_config"

cleanup() {
  rm -rf "$root"
}
trap cleanup EXIT

registry_auth_ready=false

ensure_registry_auth() {
  if [ "$registry_auth_ready" = true ]; then
    return 0
  fi
  command -v gh >/dev/null 2>&1 || {
    echo "GHCR artifact pull requires authentication, but gh is unavailable" >&2
    return 1
  }
  local login
  login="$(gh api user --jq .login 2>/dev/null || true)"
  [ -n "$login" ] || {
    echo "GHCR artifact pull requires authentication, but GitHub CLI is not authenticated" >&2
    return 1
  }
  gh auth token | docker login ghcr.io -u "$login" --password-stdin >/dev/null
  registry_auth_ready=true
}

pull_artifact() {
  local ref="$1"
  if docker pull "$ref" >/dev/null 2>&1; then
    return 0
  fi
  ensure_registry_auth
  docker pull "$ref" >/dev/null
}

hydrate() {
  local ref="$1"
  local out="$2"
  mkdir -p "$out"
  pull_artifact "$ref"
  local cid
  cid="$(docker create "$ref" /artifact/noop)"
  trap 'docker rm -f "'"$cid"'" >/dev/null 2>&1 || true; cleanup' EXIT
  docker cp "$cid:/artifact/." "$out/"
  docker rm "$cid" >/dev/null
  trap cleanup EXIT
  test -s "$out/build-receipt.json"
}

openworker="$root/openworker"
goose="$root/goose"
codex="$root/codex"

hydrate "$OPENWORKER_REF" "$openworker"
hydrate "$GOOSE_REF" "$goose"
hydrate "$CODEX_REF" "$codex"

OPENWORKER_ROOT="$openworker" OPENWORKER_SHA="$OPENWORKER_SHA" python3 - <<'PY'
import hashlib, json, os
from pathlib import Path
root=Path(os.environ["OPENWORKER_ROOT"])
receipt=json.loads((root/"build-receipt.json").read_text())
assert receipt["harness"]["name"]=="openworker"
assert receipt["source"]["revision"]==os.environ["OPENWORKER_SHA"]
for row in receipt["payload"]["files"]:
    path=root/row["path"]
    data=path.read_bytes()
    assert len(data)==row["bytes"]
    assert hashlib.sha256(data).hexdigest()==row["sha256"]
PY

python3 -m venv "$root/openworker-venv"
"$root/openworker-venv/bin/pip" install --disable-pip-version-check --no-index --no-deps "$openworker/wheelhouse"/*.whl >/dev/null
"$root/openworker-venv/bin/python" -c 'import coworker; import coworker.engine'

GOOSE_ROOT="$goose" GOOSE_SHA="$GOOSE_SHA" GOOSE_NATIVE_SHA="$GOOSE_NATIVE_SHA" python3 - <<'PY'
import hashlib, json, os
from pathlib import Path
root=Path(os.environ["GOOSE_ROOT"])
receipt=json.loads((root/"build-receipt.json").read_text())
assert receipt["harness"]["name"]=="goose"
assert receipt["source"]["revision"]==os.environ["GOOSE_SHA"]
row=receipt["payload"]["files"][0]
data=(root/row["path"]).read_bytes()
assert len(data)==row["bytes"]
actual=hashlib.sha256(data).hexdigest()
assert actual==row["sha256"]
assert actual==os.environ["GOOSE_NATIVE_SHA"]
PY
chmod 0755 "$goose/goose"
"$goose/goose" --version | grep -F "$GOOSE_VERSION" >/dev/null
"$goose/goose" --help >/dev/null

CODEX_ROOT="$codex" CODEX_SHA="$CODEX_SHA" CODEX_NATIVE_SHA="$CODEX_NATIVE_SHA" CODEX_PATCH_SHA="$CODEX_PATCH_SHA" python3 - <<'PY'
import hashlib, json, os
from pathlib import Path
root=Path(os.environ["CODEX_ROOT"])
receipt=json.loads((root/"build-receipt.json").read_text())
assert receipt["harness"]["name"]=="codex-exec"
assert receipt["source"]["revision"]==os.environ["CODEX_SHA"]
row=receipt["payload"]["files"][0]
data=(root/row["path"]).read_bytes()
assert len(data)==row["bytes"]
actual=hashlib.sha256(data).hexdigest()
assert actual==row["sha256"]
assert actual==os.environ["CODEX_NATIVE_SHA"]
patch=receipt["build"]["configuration"]["compile_only_patch"]
assert patch["sha256"]==os.environ["CODEX_PATCH_SHA"]
PY
chmod 0755 "$codex/codex-exec"
"$codex/codex-exec" --version | grep -F "$CODEX_VERSION" >/dev/null
"$codex/codex-exec" --help >/dev/null

python3 - <<PY
import json, platform, subprocess
rows=[
  {
    "harness":"openworker",
    "state":"PASS",
    "artifact_ref":"$OPENWORKER_REF",
    "source_revision":"$OPENWORKER_SHA",
    "checks":["payload-integrity","offline-wheelhouse-install","coworker-import"]
  },
  {
    "harness":"goose",
    "state":"PASS",
    "artifact_ref":"$GOOSE_REF",
    "source_revision":"$GOOSE_SHA",
    "version":"$GOOSE_VERSION",
    "checks":["payload-integrity","native-binary-sha256","version","help"]
  },
  {
    "harness":"codex-exec",
    "state":"PASS",
    "artifact_ref":"$CODEX_REF",
    "source_revision":"$CODEX_SHA",
    "version":"$CODEX_VERSION",
    "checks":["payload-integrity","native-binary-sha256","compile-patch-sha256","version","help"]
  }
]
print(json.dumps({
  "schema":"model-spelunker.sovereign-harness-preflight.v1",
  "node":"truenas",
  "architecture":platform.machine(),
  "docker_version":subprocess.run(["docker","--version"],text=True,capture_output=True).stdout.strip(),
  "model_inference_performed":False,
  "credentials_projected":False,
  "persistent_docker_auth_written":False,
  "harnesses":rows
},indent=2,sort_keys=True))
PY
