# R45 — Same session and working context across devices

## User experience invariant
A session is a **server-owned unit of work**, not a browser tab, mobile screen, Windows window, terminal, local file, or package installation. Humans, automations, and agents must attach to the same authoritative session ID and context under separately authenticated and least-privileged identities. Layout and input modality can differ without changing conversation history, task, memory scopes, artifacts or tool history.

A phone may default to voice/chat/ideation; a tablet to annotation/review; a workstation to detailed multi-panel debugging and tool observations. This is a reversible presentation preference, **not a separate session or new model prompt**. No interface may silently omit historical information, give a different approval outcome, or switch providers/tools simply because its screen is smaller.

## Canonical context, not uncontrolled replication
The R45 session snapshot describes versioned references to nine independently resolvable context classes: conversation, workspace, artifacts, memory, tool state, pending work, approval **history**, model state and DLE. The session records opaque ID, owner scope, monotonic revision, event high-water mark and SHA-256 digest of canonical context-pointer manifest. The pointer is **not content authorization**. The authoritative owner must authenticate each client, enforce per-item ACL, and retrieve/decrypt content through its existing service. Never put renewable SIWC/ChatGPT/OAuth credentials, device secrets or raw prompt/media payloads in the public manifest or DLE.

This does **not** mean that the ordinary official ChatGPT account and a separately authenticated sovereign/Agent Lab actor magically share private conversational memory. The first-party ChatGPT WebView inherits only sessions/context accessible via official ChatGPT login; actor-lab sessions use their own admitted session backend and must not scrape ChatGPT cookies, undocumented product APIs or internal memory. Cross-product context sharing requires an explicit, authorized interoperability path.

## Read-only reattachment protocol
1. Authenticate each device/audience **outside** the R45 payload, using an existing trusted identity and session/lease authority. Never copy long-lived refresh credentials or approval grants to a new device.
2. Resolve the authoritative session pointer, revision and all required context refs under that principal. Verify the canonical manifest digest.
3. Request **read-only** replay from a validated event cursor. The response must be bounded, contiguous, ordered and bound to the same session/revision/context digest.
4. On a missing/out-of-order/duplicate event, revoked authorization, or newer revision/context, fail closed and refetch authoritative state. Do not infer outcome from a stale offline view.
5. Apply R44 presentation projection locally. Local zoom, panes, HID, voice preference, window placements and caches never become independent semantic session state.
6. Any subsequent message, approval, cancel or tool command must go through the trusted existing controller with actor/session-scoped authorization, idempotency key, expected revision and independent result receipt. **No mutation path is implemented by R45.**

## Concurrent multi-device and offline requirements
- Multiple devices may observe one session concurrently, but the authoritative control plane orders and deduplicates mutations. Optimistic revision mismatch prompts refresh or explicit conflict resolution, not silent last-writer-wins.
- Read-only replay is safe to repeat; tool actions and approval decisions cannot be replayed by importing the event log.
- Pending context, tool runs, terminal/process state and workspaces must remain bound to the server workcell. Client disconnect/suspend/rotation must not kill the authoritative session unless a separately scoped request is accepted.
- Offline captures are drafts, never treated as accepted commands or durable model context until the server explicitly admits them. Do not copy sensitive history into public/browser storage to simulate continuity.
- Revocation and account switching must deny old device reads and invalidate stale leases; approval history may be visible with correct ACL but is never a transferable privilege.
- Context retention, deletion, redaction, large attachments and memory scope require user-governed policies at the authoritative service.

## Owners and remaining acceptance
- Scientific contract and three-audience parity: [Model Spelunker #265](https://github.com/SemperSupra/model-spelunker/issues/265); R45 PR #296.
- Actual shared-session and identity authority: [SupraChat #19](https://github.com/SemperSupra/suprachat/issues/19), durable [#38](https://github.com/SemperSupra/suprachat/issues/38), authenticated audience [#39](https://github.com/SemperSupra/suprachat/issues/39), and broker [#9](https://github.com/SemperSupra/suprachat/issues/9). Agent Dispatch is orchestration, not an invented second session registry.
- Browser/mobile consumer: [Android public #8](https://github.com/SemperSupra/android-publishing-foundry/pull/8), private packaging/governance #78; SupraChat browser/PWA #14.
- Source-only acceptance: frozen R45 schema, positive cross-device synthetic replay with identical context and full detail, stale/double/reordered mutation denials, free public Linux/Windows/macOS CI.
- **Not yet qualified:** live authenticated server, persistent actual context, two-device independent sign-in, multi-user ACL, revocation, secure content dereference, offline conflict recovery, real model/tool session and HIL. These gates must be proven before claiming full availability across devices.

No upstream harness fork, new client-side session database, extra model gateway, scheduler, or false production release is authorized.
