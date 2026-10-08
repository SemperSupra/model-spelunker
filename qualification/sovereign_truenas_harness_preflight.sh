#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Zero-inference, rootless preflight for admitted Model Spelunker harness
# artifacts on sovereign TrueNAS. OCI images are distribution envelopes only:
# no container daemon/socket/sudo is used.

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

REGCTL_VERSION='v0.11.6'
REGCTL_LINUX_AMD64_SHA256='8e0e62a497fcdb8048d18aa927a139613176ba0531f412bc541044e28f9856bd'

current_harness='none'
current_stage='bootstrap'
root=''

emit_failure() {
  local rc="$?"
  trap - ERR
  set +e
  PREFLIGHT_RC="$rc" PREFLIGHT_STAGE="$current_stage" PREFLIGHT_HARNESS="$current_harness" python3 - <<'PY'
import json, os, platform
print(json.dumps({
  "schema":"model-spelunker.sovereign-harness-preflight.v1",
  "node":"truenas",
  "architecture":platform.machine(),
  "overall_state":"BLOCKED",
  "failure":{
    "harness":os.environ.get("PREFLIGHT_HARNESS","unknown"),
    "stage":os.environ.get("PREFLIGHT_STAGE","unknown"),
    "exit_code":int(os.environ.get("PREFLIGHT_RC","1")),
  },
  "container_daemon_used":False,
  "model_inference_performed":False,
  "credentials_projected":False,
  "persistent_docker_auth_written":False,
  "harnesses":[],
},indent=2,sort_keys=True))
PY
  exit "$rc"
}
trap emit_failure ERR

for cmd in gh python3 sha256sum; do
  command -v "$cmd" >/dev/null 2>&1 || {
    current_stage='required-command'
    echo "required command unavailable: $cmd" >&2
    false
  }
done

arch="$(uname -m)"
[ "$arch" = 'x86_64' ] || {
  current_stage='architecture'
  echo "unsupported preflight architecture: $arch" >&2
  false
}

hydrate_helper="$(cd "$(dirname "$0")" && pwd)/hydrate_oci_layout.py"
[ -s "$hydrate_helper" ] || {
  current_stage='hydrate-helper'
  echo "hydrate_oci_layout.py was not staged beside the preflight" >&2
  false
}

root="$(mktemp -d -t model-spelunker-sovereign-harness-preflight.XXXXXX)"
cleanup() {
  rm -rf "$root"
}
trap cleanup EXIT

current_stage='registry-client'
mkdir -p "$root/tools"
gh release download "$REGCTL_VERSION" \
  --repo regclient/regclient \
  --pattern regctl-linux-amd64 \
  --dir "$root/tools" \
  --clobber >/dev/null
regctl="$root/tools/regctl-linux-amd64"
[ -s "$regctl" ]
actual_regctl_sha="$(sha256sum "$regctl" | awk '{print $1}')"
[ "$actual_regctl_sha" = "$REGCTL_LINUX_AMD64_SHA256" ] || {
  echo "regctl release digest mismatch" >&2
  false
}
chmod 0700 "$regctl"
regctl_version="$("$regctl" version 2>/dev/null | head -n 1)"

current_stage='github-package-scope'
oauth_scopes="$(gh api -i user 2>/dev/null | awk -F': ' 'tolower($1)=="x-oauth-scopes" {print tolower($2)}' | tr -d '\r')"
if [ -n "$oauth_scopes" ] && ! printf '%s' "$oauth_scopes" | grep -Eq '(^|, ?)(read:packages|write:packages)(,|$)'; then
  echo "TrueNAS GitHub credential lacks read:packages; run: gh auth refresh -h github.com -s read:packages" >&2
  false
fi

current_stage='registry-auth'
regctl_config="$root/regctl.json"
login="$(gh api user --jq .login)"
[ -n "$login" ]
gh auth token | REGCTL_CONFIG="$regctl_config" "$regctl" registry login \
  ghcr.io -u "$login" --pass-stdin >/dev/null

hydrate() {
  local name="$1"
  local ref="$2"
  local out="$3"
  local layout="$root/oci-$name"
  local hydrated="$root/hydrated-$name"
  local summary="$root/hydrate-$name.json"

  current_stage='registry-copy'
  REGCTL_CONFIG="$regctl_config" "$regctl" image copy \
    --platform linux/amd64 \
    "$ref" "ocidir://$layout:artifact" >/dev/null

  current_stage='oci-hydration'
  python3 "$hydrate_helper" "$layout" "$hydrated" \
    --ref-name artifact --summary "$summary"

  current_stage='manifest-digest'
  local expected actual
  expected="${ref##*@}"
  actual="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["manifest_digest"])' "$summary")"
  [ "$actual" = "$expected" ] || {
    echo "OCI manifest digest drift for $name" >&2
    false
  }

  current_stage='artifact-projection'
  mkdir -p "$out"
  [ -d "$hydrated/artifact" ]
  cp -a "$hydrated/artifact/." "$out/"
  test -s "$out/build-receipt.json"
}

openworker="$root/openworker"
goose="$root/goose"
codex="$root/codex"

current_harness='openworker'
hydrate openworker "$OPENWORKER_REF" "$openworker"
current_harness='goose'
hydrate goose "$GOOSE_REF" "$goose"
current_harness='codex-exec'
hydrate codex-exec "$CODEX_REF" "$codex"

current_harness='openworker'
current_stage='payload-integrity'
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

current_stage='venv-create'
if ! python3 -m venv "$root/openworker-venv" >/dev/null 2>&1; then
  command -v uv >/dev/null 2>&1 || {
    echo "python venv failed and uv fallback is unavailable" >&2
    false
  }
  uv venv --python python3 "$root/openworker-venv" >/dev/null
fi

current_stage='offline-wheelhouse-install'
if [ -x "$root/openworker-venv/bin/pip" ]; then
  "$root/openworker-venv/bin/pip" install \
    --disable-pip-version-check --no-index --no-deps \
    "$openworker/wheelhouse"/*.whl >/dev/null
else
  command -v uv >/dev/null 2>&1 || {
    echo "venv has no pip and uv fallback is unavailable" >&2
    false
  }
  uv pip install --python "$root/openworker-venv/bin/python" \
    --no-index --no-deps "$openworker/wheelhouse"/*.whl >/dev/null
fi

current_stage='import-smoke'
"$root/openworker-venv/bin/python" -c 'import coworker; import coworker.engine'

current_harness='goose'
current_stage='payload-integrity'
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
current_stage='version-smoke'
chmod 0755 "$goose/goose"
"$goose/goose" --version | grep -F "$GOOSE_VERSION" >/dev/null
current_stage='help-smoke'
"$goose/goose" --help >/dev/null

current_harness='codex-exec'
current_stage='payload-integrity'
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
current_stage='version-smoke'
chmod 0755 "$codex/codex-exec"
"$codex/codex-exec" --version | grep -F "$CODEX_VERSION" >/dev/null
current_stage='help-smoke'
"$codex/codex-exec" --help >/dev/null

current_harness='all'
current_stage='receipt'
trap - ERR

REGCTL_VERSION_OUTPUT="$regctl_version" python3 - <<PY
import json, os, platform
rows=[
  {
    "harness":"openworker",
    "state":"PASS",
    "artifact_ref":"$OPENWORKER_REF",
    "source_revision":"$OPENWORKER_SHA",
    "checks":["manifest-digest","payload-integrity","offline-wheelhouse-install","coworker-import"]
  },
  {
    "harness":"goose",
    "state":"PASS",
    "artifact_ref":"$GOOSE_REF",
    "source_revision":"$GOOSE_SHA",
    "version":"$GOOSE_VERSION",
    "checks":["manifest-digest","payload-integrity","native-binary-sha256","version","help"]
  },
  {
    "harness":"codex-exec",
    "state":"PASS",
    "artifact_ref":"$CODEX_REF",
    "source_revision":"$CODEX_SHA",
    "version":"$CODEX_VERSION",
    "checks":["manifest-digest","payload-integrity","native-binary-sha256","compile-patch-sha256","version","help"]
  }
]
print(json.dumps({
  "schema":"model-spelunker.sovereign-harness-preflight.v1",
  "node":"truenas",
  "architecture":platform.machine(),
  "overall_state":"PASS",
  "distribution_transport":"regctl-ocidir",
  "registry_client":os.environ["REGCTL_VERSION_OUTPUT"],
  "container_daemon_used":False,
  "docker_socket_used":False,
  "sudo_used":False,
  "model_inference_performed":False,
  "credentials_projected":False,
  "persistent_docker_auth_written":False,
  "harnesses":rows
},indent=2,sort_keys=True))
PY
