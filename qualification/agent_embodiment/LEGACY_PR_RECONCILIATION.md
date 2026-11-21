# Qwen Code legacy PR reconciliation — source-first integration ledger

**Recorded:** 2026-11-21. **Scope:** public Model Spelunker repository only. This is a non-destructive source/DLE reconciliation report. It does **not** close PRs, delete branches, import unverified experiments, confer model competence, or authorize an owner-host action.

## Already integrated mainline (observed prior accepted CI)

| Change | Main merge SHA | Accepted scope | Remaining caveat |
|---|---|---|---|
| [#258](https://github.com/SemperSupra/model-spelunker/pull/258) | `eebb85a2845a70c31657b659d9aead195b782294` | Pinned Qwen Code 0.28.3 CLI; Qwen3 32K context; separately reported strict terminal oracle | A wire PASS is not a model answer PASS; native R10 had `EXPECTED_WITH_EXTRA` |
| [#264](https://github.com/SemperSupra/model-spelunker/pull/264) | `a550d95575bb85750635e15d8f97e6d1487070cf` | Linux public synthetic installer/verify/teardown, protected settings/native bytes, strict two-hop model task | GHA env guards are not authenticated production admission |
| [#266](https://github.com/SemperSupra/model-spelunker/pull/266) | `02083472f9ab8bed1b6442482f631c3d46a6cbe1` | Rootless, pinned OCI carrier | Package integrity alone does not qualify an actor |
| [#267](https://github.com/SemperSupra/model-spelunker/pull/267) | `5fc49ea39703e4359eaa4cc695ec4ea4bf17a15d` | Main-only GHCR publish / remote fetch admission | Publisher and DLE callback must be observed, not inferred |
| [#268](https://github.com/SemperSupra/model-spelunker/pull/268) | `b92e9b8dc2bec74813584ad2e1177519b032dad3` | Exact digest-bound DLE callback to Foundry #147 | Production/actor admission deliberately not granted |
| [#269](https://github.com/SemperSupra/model-spelunker/pull/269) | `e9b1591e1a1e219f5daf6295a6e1a23445cc8937` | Actual anonymous immutable GHCR read / native Qwen version | Does not include model inference |
| [#270](https://github.com/SemperSupra/model-spelunker/pull/270) | `28cbf7577ee9ef43411c6c0ed9e6276343060673` | Precise independent Windows/Linux/OCI workflow input scopes | Does not change task competence |
| [#271](https://github.com/SemperSupra/model-spelunker/pull/271) | `9d5796e21ce7b642d9c17dcc8572baad984a4c7c` | Four independent actual Qwen model-backed two-hop trials, 4/4 success | Earlier first-attempt WRONG_TOOL_COUNT/WRONG_FINAL remains authoritative |

Current immutably admitted public source: `ghcr.io/sempersupra/model-spelunker-harness-qwencode@sha256:506ef11f6cde829e8f31e3c9b9ca83903278b5a604038aaeda49271e538d3954` (Linux amd64 **only**), recorded at [Foundry #147](https://github.com/SemperSupra/model-spelunker/issues/147#issuecomment-7064633187).

## Open stacked/historical Qwen PRs — **retain, do not blindly merge**

| PR | Actual changed files / primary purpose | Disposition and exact outstanding comparison |
|---|---|---|
| [#259](https://github.com/SemperSupra/model-spelunker/pull/259) | R10 workflow, `final_oracle.py`, `run_context32.sh` | **Partly superseded** by #258 source-integrated strict final frame oracle. Check code equality or distinct test coverage before closing. Historical native model FAIL remains. |
| [#260](https://github.com/SemperSupra/model-spelunker/pull/260) | Five-file R12 two-hop workflow, critic, final oracle, native run script, wire proxy | **Distinct scientific fixture** from #264 even though #264 proves 2-hop task. Preserve for source comparison and task-envelope audit. |
| [#261](https://github.com/SemperSupra/model-spelunker/pull/261) | R12 workflow, lineage oracle, two-hop runner | **Evidence partly reused** by #264's independently sourced strict lineage oracle; its exact task-runner and GH Actions changes still require review. |
| [#262](https://github.com/SemperSupra/model-spelunker/pull/262) | R10 workflow, causal diagnostic and runner | **Diagnostic research**, not unconditional model-capability improvement. Retain negative-source evidence; review causal diagnostic before selective reuse. |
| [#263](https://github.com/SemperSupra/model-spelunker/pull/263) | R17 typed tool-result projection, workflow, R10 runner | **Future experimental variant**; source review and independent model success still required before merging into baseline. |
| [#221](https://github.com/SemperSupra/model-spelunker/pull/221) | 11-file portable Linux/Windows capsule kit/workflows/PS5.1 scripts/route compiler | **Non-destructive staged reconciliation**: already-main `kit.py` and pinned manifest plus **merged** clean-main-based [#273](https://github.com/SemperSupra/model-spelunker/pull/273) (merge `f513ceef203f3f44c2361426234dca81f5570a26`) adopting original `Invoke-QwenCapsule.ps1` and `Observe-QwenHost.ps1`; keep remaining compiler/routes/workflows experimental. Do **not** import original branch whole. |
| [#229](https://github.com/SemperSupra/model-spelunker/pull/229) | Public Hyper-V/PS Direct evidence provenance report, reduction and critic | Separate historical guest evidence, **not** actual physical authorized Hyper-V native Qwen test. Compare before integration. |

**This ledger is an audit classification, not a detailed line-level semantic merge claim.** For each PR, use its exact HEAD and changed-file patch, check history/actual overlap against current main, preserve negative results, then either produce a small reviewed clean-main integration or close it with exact superseding references. Never delete a source/branch until all independent DLE evidence is relocated/linked.

## Next admission boundaries

1. **R26 merged Windows PS5.1 reference** [#273](https://github.com/SemperSupra/model-spelunker/pull/273): public CI [#44928571374](https://github.com/SemperSupra/model-spelunker/actions/runs/44928571374) PASS; synthetic portable source/manifest ZIP, native Windows CLI `--version`, OPAV/negative controls on disposable hosted `windows-2025` GHA. This is **not** a real private Windows host or Hyper-V guest qualification. Mode=Production must fail closed until independently pinned/authorized controller workcell exists.
2. **Physical Win/Hyper-V guest HIL**: only after Agent Dispatch externally grants workcell identity and lease; no forged user-provided verifier, root credential or runner env attestation. Test apply, tamper, owned rollback, interrupted state, and external oracle on a *disposable guest*.
3. **Sovereign runtime crossovers**: observe available version/route/provider context and capabilities, then independently prove model/tool protocol, tool lineage, strict result and resource envelopes. No claims of access to unprobed local hosts.
4. **Broader harness/MCP deferred**: [Model Spelunker #272](https://github.com/SemperSupra/model-spelunker/issues/272) and [Tool Belt #172](https://github.com/SemperSupra/mcp-projection-dev/issues/172) own pinned source-first MCP client/server/bridge feature census and later Tool Belt integration. Future until promoted.
5. **Real Agent Dispatch end-to-end**: [Agent Dispatch #104](https://github.com/SemperSupra/agent-dispatch-private/issues/104) owns mission command admission, delegations, workcell lifecycle, DLE and authorization.

## Non-negotiable DLE invariants

Durable, Legible, Executable; GitHub authority; exact pinned source/run/receipt identity; clear operator vs automated authority; no paid/private CI; no production admission from `GITHUB_ACTIONS`, `CI` or MCP tools; fail-closed task-vs-infrastructure-vs-distribution classifications; settings and payload integrity; no credentials/raw private context in public artifacts; idempotent owned cleanup and foreign-resource preservation. Each source milestone must reconcile its owning issue and a separate exact run receipt.
