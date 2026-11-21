# Qwen Code packet validation and evidence status (no wave planner)

Owner [Model Spelunker #224](https://github.com/SemperSupra/model-spelunker/issues/224) / de-duplication [#240](https://github.com/SemperSupra/model-spelunker/issues/240).

This subtree is a **source-neutral Qwen-domain validation and evidence ledger**, not a second packet scheduler or actor-baton generator. It rejects source-scope collisions, private work on public Actions, unbounded weak-model task envelopes, unverified `DONE_VERIFIED`, false `FAILED`, missing dependencies and unauthorized placement.

**One wave-planning source of truth:** the *existing* [SupraGoFlow Go `batch-wave/v1` compiler](https://github.com/SemperSupra/supragoflow/pull/61) (private coordination authority [IaC #603](https://github.com/mark-e-deyoung/infrastructure-as-code-private/issues/603)), whose public source is SHA-pinned and was actually called in [Qwen adapter PR #239 / CI #44878299706](https://github.com/SemperSupra/model-spelunker/actions/runs/44878299706). The adapter under `qualification/qwen_wave_adapter/` maps only properly classified READY Qwen tasks into that existing Go format; it never selects a subset or dispatches jobs, and the current R5 packet set correctly has **zero READY public tasks**. Actual work effects remain under signed/external Agent Dispatch admission, never a Go parser result.

## One weak actor per context

Read root/scoped `AGENTS.md`, the exact authoritative issue, and one externally prepared Go `batch-wave` baton. Confirm source SHA, uniquely owned branch/file/resources, explicit bounded effect, prerequisites and independent oracle; stop if admission missing. Small-model work cards should stay at <=8 tool calls, <=1600 task-specific context tokens and <=20 minutes, but **the full Qwen Code system+tools prompt may be much larger**; qualify actual model/runtime request size separately. Execute only admitted effects inside owned disposable workcells, retain independent witnesses, publish the six-line GitHub DLE receipt and stop. Do not ingest whole conversations or mark self-assessed prose PASS.

The supervising actor gives independent tasks to separate public/free GHA workers, max two concurrent until resource headroom is qualified. Long model/VM tasks do not block fast static critics. Failures are recorded and analyzed rather than silently retried or counted as completed throughput. Do not edit other actors' branches.

## Current pure, non-executable commands

```sh
python3 qualification/qwen_batches/contract.py validate
python3 qualification/qwen_batches/contract.py status
python3 qualification/qwen_batches/contract.py hash
python3 -m unittest discover -s qualification/qwen_batches -p test_contract.py -v
```

The obsolete Python `candidates` and `cards` actions and `plan_candidates` function are **removed**, after qualified existing-Go interoperability. `status` only reports counts, no task selection and no execution grant.

Use the existing Go adapter for *public-safe synthetic* tasks only. Private IaC owner host/guest and MCP acceptance remain separate; no private data or credentials in public Actions. Source-bound run/commit/job status verification is independently implemented by [#234 / PR #236](https://github.com/SemperSupra/model-spelunker/pull/236) and must not be mistaken for semantic artifact content attestation.

## Ledger and acceptance boundary

Public source-neutral packet states include four verified subclaims (tool wire, route security, direct model tool selection, guest provenance), two independently witnessed model failures (full Qwen CLI with CPU Qwen3:1.7b and 29KB context direct model timeout), and two separate admission-blocked H2 guest/private-site effects. They are **not** claims that the whole Qwen Code environment is ready to install.

Keep dated exact source/run references in [issue #224](https://github.com/SemperSupra/model-spelunker/issues/224); domain security source and target status are governed by [#220](https://github.com/SemperSupra/model-spelunker/issues/220), private [IaC #601](https://github.com/mark-e-deyoung/infrastructure-as-code-private/issues/601), and [Agent Dispatch #748](https://github.com/SemperSupra/agent-dispatch-private/issues/748). Do not auto-merge draft source, issue credentials, install persistent host tools or bypass the still-unresolved LiteLLM credential incident.

Every `DONE_VERIFIED` or `FAILED` receipt requires independent source-bound positive/negative evidence; actual guest boot and site-model/tool use require their own external admit/verify/cleanup gates.
