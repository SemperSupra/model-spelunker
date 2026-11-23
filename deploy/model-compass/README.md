# Model Compass — disposable, stateless OCI deployment (R0)

Authority: [Model Spelunker #304](https://github.com/SemperSupra/model-spelunker/issues/304). Consumer: [private TrueNAS App Foundry #355](https://github.com/SemperSupra/truenas-app-foundry-private/issues/355) under existing generic lifecycle #274/#290/#267. Windows standalone consumer [private IaC #666](https://github.com/mark-e-deyoung/infrastructure-as-code-private/issues/666); model qualification/provenance [IaC #665/#668](https://github.com/mark-e-deyoung/infrastructure-as-code-private/issues/665).

## Deployment decision

**Primary:** TrueNAS SCALE Apps, with **TrueNAS App Foundry as the sole source rendering, image/IR identity, materialization, ownership/plan/apply/verify and lifecycle authority.** The product contributes a native Custom App Compose *deployment artifact candidate* and immutable OCI image. Foundry must lower/qualify this against an exact `truenas/apps` source and `truenas/middleware`/TrueNAS target before claiming native acceptance. Its existing generic lifecycle must perform create/start/stop/update/redeploy/remove/reinstall; NO independent product-specific TrueNAS apply script.

**Secondary:** rootless Podman Quadlet on a separately administered Linux or free Oracle VPS. This is an alternative target artifact of the same OCI image, **not a qualified Foundry Quadlet lowering adapter** and not a supported way to run this app as an unmanaged second supervisor directly on TrueNAS. Third parties may choose it only after target-qualified source/HIL. No cloud-exposed model routes or credentials.

**Clients:** Windows PS5.1 launcher and model-compass MCP/HTTP clients, BigMac and other agents use the TrueNAS primary or explicit local fallback. Agent Dispatch is an optional *downstream* consumer; model-compass runs without it.

## Container and external durable data

- Build context: repository root, Dockerfile `deploy/model-compass/Dockerfile`; source consists of exact `cmd/model-compass` Go executable plus a separate read-only `cmd/compass-http` adapter. No duplicated routing engine, database, scheduler, binary download, credential broker or model weights.
- Release image must be built from exact source and resolved/published/selected by immutable OCI `sha256` digest. The Dockerfile's versioned Go base must also be pinned by digest during trusted release packaging; public PR CI qualification does not approve registry publication.
- Runtime: `scratch`, statically linked Go binaries, UID/GID 65532 in TrueNAS Compose, read-only rootfs, all caps dropped, no new privileges, 64 PID limit, ~256MiB memory; no Docker socket, GPUs, host privileged/devices or host network. `/tmp` is tmpfs only for native Compose; no state inside image or writable layer.
- External owner-controlled **ZFS dataset** mounted read-only at `/state`. Private state may be managed *externally* by an authorized ingest/validation process using atomic replacement, never by this disposable request handler. `/state/snapshot.json` is optional: if missing/malformed it returns 503/UNKNOWN, not fabricates model/artifact registration. The endpoint marks supplied snapshots `EXTERNAL_SNAPSHOT_UNVERIFIED` because file JSON alone is not a signed MAF/Spelunker attestation.
- External **token file** mounted read-only at `/run/secrets/compass_token`, mode 0400 for Compose UID 65532, at least 32 nonempty bytes. No token env/argv, no baked secret or fallback anonymous mode. Read on each request so token rotation does not require immutable container rebuild. On rootless Quadlet, `UserNS=keep-id` and `User=%U` retain local account access to a mode 0600 secret.
- TrueNAS bind volume host paths are private site configuration, **not** committed to public Git. Before first deployment, create dedicated datasets/ACLs, signed source/qualified immutable image and local token; do not let app lifecycle remove owner-retained ZFS data by default. Bind host published port to `127.0.0.1:18088` only. Windows network access requires a separately authorized authenticated tunnel/reverse proxy with client policy. Do not publish port on 0.0.0.0 or open Oracle OCI security groups.

### API contract (all except liveness require `Authorization: Bearer <token>`)

- `GET /healthz`: minimal adapter liveness only; `backend_ready=UNKNOWN`. Does NOT assert runtime/backend/qualified model.
- `POST /mcp`: stateless JSON-RPC 2.0 single-request MCP over HTTP, fixed allowed methods/tools only, 16KiB bound; calls the **existing** model-compass `-mcp` executable without a shell and bounded execution/output. No Agent Dispatch.
- `GET /v1/venue/{id}`: existing catalog as static advisory, `qualification=UNKNOWN`, `route_status=UNVERIFIED_STATIC_CATALOG`.
- `POST /v1/recommend`: validated task constraints, existing model-compass ranking as explicitly **advisory only**, `automatic_admission=false`, `qualification=UNKNOWN`. Do not treat current hardcoded source endpoint as verified. The Go catalog includes a stale retired Strata :8085 route; real route/source verification remains [IaC #214](https://github.com/mark-e-deyoung/infrastructure-as-code-private/issues/214) and [Spelunker #303](https://github.com/SemperSupra/model-spelunker/issues/303). No governed `resolve` endpoint until true Foundry identity + Spelunker binding/admission gates exist.
- `GET /v1/snapshot`: external private ZFS projection in bounded form, explicitly *unverified*.
- All authenticated endpoints are bounded at 8 concurrent requests, ~8s subprocess timeout, read/write body limits, fixed method/tool allowlist. No arbitrary code execution tools or path selection.

## Rebuild / rollback / statelessness acceptance

Disposability means every container can be deleted/rebuilt and recreated from the same **immutable image + external dataset + external token**, and the private snapshot is unchanged. Source tests verify token rotation, snapshot availability after a new server instance, authentication, nonqualified advice and denied arbitrary tools. A public disposable Docker test must validate image build, health response, 401 without token, authenticated snapshot, read-only rootfs and state retained after container deletion/recreate. Podman Quadlet requires independent target-profile qualification before supported status.

For native TrueNAS, Foundry acceptance remains **F0–F6** against exact TrueNAS version: source rendering/normalized Compose fingerprint, identity-bound artifact, no-foreign-state plan, create/readback, clean stop/start/redeploy, token rotation and ZFS state preservation, NOOP convergence, upgrade/rollback, remove/reinstall with explicit retained-state policy and no Host ZFS deletion. Published CI only verifies code/container candidate; it does **not** claim TrueNAS HIL.

## Local or disposable-cloud validation

```sh
cd cmd/compass-http
GOPROXY=off GOSUMDB=off go test -count=3 ./...
GOPROXY=off GOSUMDB=off go vet ./...
cd ../..
docker build -f deploy/model-compass/Dockerfile -t model-compass:local .
```

Free public GitHub Actions executes tests on Linux/Windows/Mac and Docker on Linux; any Quadlet or TrueNAS VM qualification must be separately evidenced and target-pinned. No paid private GHA or private model credentials. The CI uses synthetic tokens and fixtures only. For production, reference the **immutable approved image digest**, NEVER `latest` or a floating branch/ref. Application config/source, private model endpoint inventory and the durable GitHub DLE remain external authorities.

## Deployment semantics

`deploy/model-compass/truenas-compose.yaml` is an **input to Foundry**; replace environment interpolation with Foundry-owned exact materialization values, not manually with ad-hoc on-box Docker commands. Do not treat a green `docker compose config` as TrueNAS Apps native lifecycle acceptance.

`deploy/model-compass/model-compass.container` is a **separate rootless Podman target candidate**; replace the placeholder image identity and place it under the Linux operator's user Quadlet directory only after target profile qualification. Quadlet `ReadOnly=true`, `ReadOnlyTmpfs=false`, dropped capabilities, `UserNS=keep-id`, `Pull=never` ensure the specified image is local and state remains host-owned. No host `sudo`, daemon injection, Docker socket or uncontrolled update loop is required by the unit. On Oracle, outbound private routing/visibility is not assumed; an off-site *observer* cannot read sovereign backend status unless explicitly admitted authenticated transport exists.

## Known missing gates

TrueNAS official-source-shaped app inventory/export not yet committed; container/source GitHub CI still separate from Foundry F0–F6; image immutable digest promotion, Quadlet generator/render HIL, exact TrueNAS target HIL and private provenance/admission integration pending. The source-shape must be reconciled with existing Foundry consumer templates, not implemented as a competing installer. No private GHA minutes or physical site access exercised.
