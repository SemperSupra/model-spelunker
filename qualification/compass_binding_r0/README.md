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

## R2 required evidence handles

Even the synthetic matching oracle requires nonempty observation, registry and interview evidence references and SHA-256-shaped configuration/host/tool digests. A missing evidence reference is UNKNOWN or MISMATCH, not a verified route. **These handles and digest-shape checks are not authentication**; the private consumer must independently verify source trust, signature/catalog revision, timestamps, and component-hash completeness. An eligible result is only an evidence-conditioned recommendation, never permission to execute tools or proof that an unloaded model is currently serving.

## R3 trust-boundary correction

Synthetic red-team source-only tests showed that accepting a raw `managed` admission Boolean was indistinguishable from authenticated workcell authority, and that rendering `privately_adopted` as generic `APPROVED` obscured its distinct status from Foundry public catalog approval. The R3 contract **never grants managed execution** from a caller-provided Boolean: `managed` deterministically returns `EXTERNAL_AUTHORITY_REQUIRED` and `Eligible=false`, even if a legacy `Admission=true` input is supplied. Only a separately authenticated and explicitly bounded execution controller may admit a managed workcell; the oracle is not that controller. The direct evidence-conditioned suggestion remains independent of Agent Dispatch, without granting filesystem, network or tool authority.

Approval labels are now `PUBLIC_APPROVED`, `PRIVATE_ADOPTED`, `NOT_APPROVED` and `UNKNOWN`; `PRIVATE_ADOPTED` is not evidence of public OCI publication and retains private provenance/rights requirements. The actual live consumer must not equate arbitrary evidence-reference strings or SHA-shaped digests with verified source authenticity.
