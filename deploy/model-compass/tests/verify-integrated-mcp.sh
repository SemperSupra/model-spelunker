#!/usr/bin/env bash
# Public-safe, offline-inference integration oracle. Only this disposable runner,
# synthetic secrets, and a self-built immutable source image are touched.
set -euo pipefail

image="${COMPASS_TEST_IMAGE:-model-compass:integration}"
base="${RUNNER_TEMP:-$(mktemp -d)}/compass-stdio-oci-integration"
mkdir -p "$base/state"
printf '%s\n' '{"schema":"synthetic","receipt":"persist-both-runtimes"}' > "$base/state/snapshot.json"
printf '%064d\n' 1 > "$base/token"
printf 'Authorization: Bearer %064d\n' 1 > "$base/auth-current"
printf 'Authorization: Bearer %064d\n' 2 > "$base/auth-next"
sudo chown -R 65532:65532 "$base/state" "$base/token"
sudo chmod 0400 "$base/token"

cleanup() { docker rm -f compass-integrated-smoke >/dev/null 2>&1 || true; }
trap cleanup EXIT
for rep in 1 2; do
  docker run --detach --name compass-integrated-smoke \
    --read-only --user 65532:65532 --cap-drop ALL \
    --security-opt no-new-privileges:true --pids-limit 64 --memory 256m \
    --tmpfs /tmp:rw,noexec,nosuid,size=8m \
    -p 127.0.0.1:18097:8088 \
    -v "$base/state:/state:ro" \
    -v "$base/token:/run/secrets/compass_token:ro" \
    "$image" >/dev/null

  ready=0
  for i in $(seq 1 30); do
    if curl --fail --silent --show-error --max-time 1 http://127.0.0.1:18097/healthz >/dev/null 2>&1; then
      ready=1; break
    fi
    sleep 1
  done
  if test "$ready" != 1; then docker logs compass-integrated-smoke; exit 1; fi

  printf '%s\n' \
    '{"jsonrpc":"2.0","id":10,"method":"ping"}' \
    '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
    '{"jsonrpc":"2.0","id":11,"method":"tools/list"}' |
    docker exec -i compass-integrated-smoke /usr/local/bin/model-compass -mcp > "$base/stdio-success.jsonl"

  python3 - "$base/stdio-success.jsonl" <<'PY'
import json,sys,pathlib
messages=[json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
assert len(messages)==2,messages
assert [x["id"] for x in messages]==[10,11], messages
assert all(x["jsonrpc"]=="2.0" and "error" not in x for x in messages),messages
assert any(x.get("name")=="recommend_models" for x in messages[1]["result"]["tools"]),messages
print("PASS: OCI's exact MCP stdio ping + notification silence + tools/list")
PY

  printf '%s\n' \
    '{"jsonrpc":"1.0","id":12,"method":"ping"}' \
    '{not-json}' |
    docker exec -i compass-integrated-smoke /usr/local/bin/model-compass -mcp > "$base/stdio-errors.jsonl"
  python3 - "$base/stdio-errors.jsonl" <<'PY'
import json,sys,pathlib
messages=[json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
assert len(messages)==2,messages
assert {x["error"]["code"] for x in messages}=={-32600,-32700}, messages
print("PASS: OCI's exact MCP stdio rejects malformed/version-invalid requests")
PY

  # HTTP bridge is stateless JSON-RPC over HTTP (NOT claimed MCP Streamable HTTP).
  curl -fsS -H @"$base/auth-current" \
    -H 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":21,"method":"ping"}' \
    http://127.0.0.1:18097/mcp > "$base/http-ping.json"
  python3 - "$base/http-ping.json" <<'PY'
import json,sys,pathlib
response=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert response["jsonrpc"]=="2.0" and response["id"]==21,response
assert response["result"]=={},response
print("PASS: external HTTP JSONRPC bridge calls exact bundled stdio MCP server")
PY

  curl -fsS -H @"$base/auth-current" \
    -H 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":22,"method":"tools/call","params":{"name":"get_sommelier_specials","arguments":{}}}' \
    http://127.0.0.1:18097/mcp > "$base/http-tool.json"
  python3 - "$base/http-tool.json" <<'PY'
import json,sys,pathlib
response=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert response["jsonrpc"]=="2.0" and response["id"]==22,response
result=response["result"]
assert len(result["content"])==1 and result["content"][0]["type"]=="text"
assert isinstance(json.loads(result["content"][0]["text"]),list)
print("PASS: bundled MCP tool response retained through authenticated HTTP")
PY

  test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:18097/mcp)" = 401
  curl -fsS -H @"$base/auth-current" \
    http://127.0.0.1:18097/v1/snapshot | grep -q persist-both-runtimes
  test "$(docker inspect -f '{{.Config.User}}' compass-integrated-smoke)" = "65532:65532"
  test "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' compass-integrated-smoke)" = "true"
  docker rm -f compass-integrated-smoke >/dev/null
done
test "$(cat "$base/state/snapshot.json")" = '{"schema":"synthetic","receipt":"persist-both-runtimes"}'
echo "PASS: two disposable OCI instances include exact upstream MCP fixes; external state retained; no AD or backend models accessed"
