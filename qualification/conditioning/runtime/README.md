# Conditioning Lab — disposable ComfyUI runtime (RDT&E)

This is the product-owned runtime under [Model Spelunker #195](https://github.com/SemperSupra/model-spelunker/issues/195), reusing DOE [#193](https://github.com/SemperSupra/model-spelunker/issues/193). It has **NOT** been installed on the owner’s TrueNAS, published as a released OCI product, qualified on NVIDIA CUDA, or used to generate a real FLUX/Z-Image asset.

## Deployment authority

Primary: an official TrueNAS Apps **community-source-shaped application** at `catalog/ix-dev/community/conditioning-lab`. The only authorized inventory, source renderer, materializer, deployment artifact and lifecycle manager is [TrueNAS App Foundry](https://github.com/SemperSupra/truenas-app-foundry), governed by private #274 (F0–F6), #290 (observe→plan→apply→verify), #328 (catalog UX/API) and exact target/version #267/#282. **OFFICIAL SOURCE SHAPE does not mean officially accepted/published in the TrueNAS catalog.** The current `ix_values.yaml` deliberately contains non-pullable `sha256:000…` placeholders until all candidate image digests are independently built, pulled back, reviewed, and accepted through Foundry. A human must not install the seed.

Secondary target projections: ordinary OCI/Docker/KVM and future macOS Comfy MPS or MLX, using the same explicit workload/capability/state identities; each target separately qualified. Do **not** create a local Compose installer or second lifecycle controller.

## Component separation

| Component | Lifetime | Responsibility | Network and mounts |
|---|---|---|---|
| Go controller | Restartable, stateless process | Accessible UI, API/agent capabilities, bounded batches, idempotency, native Comfy queue adapter, immutable output hashes, restart ambiguity | Only published interface (behind approved TLS/auth ingress), durable TrueNAS-managed `/state`, token via protected read-only file. No GPU or model filesystem |
| ComfyUI worker | Replaceable/disposable | Execute bounded allowed workflows on CPU or a specifically admitted single GPU. Built-in queue runs work | Private app network; never publish raw `/prompt`. Writable disposable `/data`, hydrated models mounted read-only, no provider credentials or auto-download |
| MAF hydration sidecar | One-shot | Resolve approved OCI digest; delegate fetch/verify/promote to pinned **Model Artifact Foundry** `tools/hydrate.py` | Approved `approved.json` read-only, durable content-addressed model store. No GPU, no worker contact |
| TrueNAS App Foundry | Existing external authority | Version-aware catalog source validation, immutable OCI materialization, inventory, host observe→plan→apply→verify and lifecycle | No site-specific host path or credential belongs in this public product repository |

State is *deliberately* durable: stateless/disposable **containers** do not mean forgetting accepted user jobs or completed artifacts. A single Flock owner protects `ledger.json`; atomic file replace and fsync protect entries. On interrupted RUNNING work, controller marks `UNKNOWN_NEEDS_RECONCILIATION` and stops automatic duplication. The current queue is bounded (max 16 per batch, one active worker). Production-grade quota/capacity policies and user identities require authority review before exposing outside LAN/TLS boundary.

## Three audiences

- **Human UI/UX/a11y:** semantic HTML on `GET /`; labeled seed, fieldset/radio selection, keyboard-native submit and status links; Basic authentication plus independent Origin/CSRF checks. This is a **functional accessibility baseline**, **not yet WCAG 2.2 AA qualified**. Screen-reader/keyboard journey, focus management, contrast, large text, error announcements and alternative-language review are future acceptance tests before production.
- **Automation API/DX:** `Authorization: Bearer <token>`; `GET /api/v1/capabilities`, `POST /api/v1/batches`, `GET /api/v1/jobs`, `GET /api/v1/jobs/{id}`, `GET /api/v1/jobs/{id}/image`, `POST /api/v1/jobs/{id}/cancel`. `/healthz` confirms controller liveness only, **not GPU/worker readiness**. Job IDs are opaque. No raw graph ingestion allowed.
- **Agents:** `/api/v1/capabilities` returns allowlisted workflow and bounds; job receipts include state/digests, not model self-scores. Agent cannot elevate model admission or invoke arbitrary tools by constructing JSON.

For a bounded synthetic pair, an **authorized** client may submit (the token is provisioned via protected local file, never checked into Git):

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $CONDITIONING_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"example-paired-0001","jobs":[{"workflow":"toy-cnn-v1","seed":31,"variant":"base","size":64},{"workflow":"toy-cnn-v1","seed":31,"variant":"modified","size":64}]}' \
  https://conditioning.example.invalid/api/v1/batches
```

On restart after uncertain native queue acknowledgment, `UNKNOWN_NEEDS_RECONCILIATION` requires human/authorized agent observation; no blind rerun. Running-job cancellation is a request, not guaranteed termination of an already submitted image.

## Reproducible build and public free CPU tests

- `runtime/Dockerfile` overlays only the vetted tiny PyTorch CNN node on the upstream `romkey/comfyui-docker:0.38.0-cpu` **resolved by digest**. Disable manager, auto node downloads and partner API nodes. The CPU test uses ephemeral `/data`, non-root process, cap-drop, no new privileges, localhost-only mapped port.
- `runtime/smoke.py` checks real Comfy `/object_info`, `/prompt`, `/queue`, `/history` and `/view`, and verifies two distinct 64×64 PNGs. **This proves only synthetic neural network / queue / output path**.
- Go controller `go test -race -count=1 -v ./...` separately checks authentication, idempotency, browser CSRF, single-owner lock, durable ledger, restart ambiguity and native queue adapter using a fake Comfy API.
- `runtime/sidecar/test_gate.py` tests strict MAF approval/digest rejection without any model downloads. Its container build must independently pass.
- Native TrueNAS catalog source render runs against an **exact pin** of public `truenas/apps`; verifies normalized Compose structure/security without pulling candidate model or launching physical TrueNAS.

## Model acquisition and future genuine generator runs

Model Artifact Foundry approved v1 catalogue selects a logical ID and `ghcr.io/sempersupra/...@sha256:<exact>`. The short-lived sidecar invokes the pinned MAF `tools/hydrate.py` with pinned ORAS, which independently verifies bundle files, advances the content-addressed blob, and then atomically selects model. No arbitrary HF URL, secrets to ComfyUI, silent promotion or model bytes in Git.

Only after verified digest-pinned worker/sidecar OCI images, Foundry-native F0–F6 source/render qualification, exact TrueNAS version/host GPU availability, actual model rights + data hashes, and local owner operation authority may the app run real generators. Inference success, scientific quality and human approval are different gates. The first proposed pairing remains FLUX.2 Klein original Qwen3-4B conditioner vs Heretic at fixed seed; do not auto-enable Z-Image/Krea, high-load video or paid cloud.

**Current truth:** candidate/source/test only, public CPU toy image test PASS, CUDA/model compatibility and native TrueNAS runtime UNKNOWN.
