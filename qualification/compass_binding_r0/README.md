# Model-compass evidence join: synthetic R0

This directory is an **independent public-safe source-only contract oracle** under Model Spelunker #297, consumed by the private sovereign IaC #668 workset. No runtime, network, credentials, private host inventory, model bytes, OCI publication, Agent Dispatch import, or deployment is involved.

The `Evaluate` function consumes supplied, authenticated **external evidence**. This module **does not authenticate** the provenance of the input or implement a registry, model router, validator, scheduler, admissions, or executable harness. Current statuses are synthetic projection states, **not actual task qualification**.

- `direct`: Agent Dispatch is absent; no AD RPC, package or admission dependency. Qualified model-route suggestion is possible when exact artifact identity, configured-actor evidence and independent safety criteria match. Direct model route recommendation **does not authorize tool/workcell actions**.
- `managed`: admitted execution evidence is an additional requirement and cannot be inferred from artifact approval or task success.
- Preserve OCI descriptor vs content-manifest representation identity kinds; separate file SHA from descriptor.
- Strict comparison of artifact identity and runtime/harness/task/config/host/tool dimensions. A model alias is never an identity.
- Process generation must equal observed attestation generation to prevent stale startup identity reuse.
- All synthetic receipts omit personal/local information and contain fake hashes.

Run: `go test -count=3 ./...` and `go vet ./...`.

Before use in any real model-compass or route authorization, add cryptographically bound trusted evidence-source verification, freshness/failure semantics, immutable catalog and Spelunker receipt adapters, real runtime startup attestation, and direct-lane network/tool policy enforcement. Approval of a model artifact cannot imply permission to execute an agent. This does **not** modify existing authority in MAF-private #6/#7/#11 or Agent Dispatch #104.

Source authority: SemperSupra/model-spelunker#297, #139; private IaC #665/#668. No automatic DLE promotion or HIL claims.
