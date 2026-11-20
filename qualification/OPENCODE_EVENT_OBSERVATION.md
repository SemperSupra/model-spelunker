# OpenCode V2 event projection (source-only, experimental)

Issue: [#204](https://github.com/SemperSupra/model-spelunker/issues/204). Governing configured-actor interview: [#139](https://github.com/SemperSupra/model-spelunker/issues/139); Agent Dispatch privately owns configured-actor admission and selection (#104). Observatory owns independent system/target sensors (private `mark-e-deyoung/ghidra-tools#4`). This increment adds **no scheduler, runtime listener, model routing, new receipt schema, or actor admission**.

OpenCode V2 documents its session/tool/event APIs at <https://opencode.ai/docs/api>. The public API describes event types, but cannot prove that a particular installed OpenCode binary emits them accurately. V1 and V2 are **not** interchangeable. Before live deployment, pin exact V2 package/build and confirm live event envelopes and source session identity on a disposable target.

## No-model offline check

From the repository root:

```sh
PYTHONPATH=. python -m unittest qualification.test_opencode_event_projection -v
python qualification/opencode_event_projection.py --input /path/to/authorized/synthetic-v2-events.jsonl
```

The CLI accepts bounded newline-delimited JSON objects shaped as `{ "type": "session.tool.called", "properties": { "sessionID": "opaque" } }`. It reads existing workcell evidence only. It does not start OpenCode, discover models, connect to a machine, access GitHub credentials or execute a tool. It prints one deterministic JSON summary, with no raw event fields. It rejects invalid/malformed records, unbounded input, multiple session identities and duplicate JSON keys, including nested duplicates.

**Security/privacy:** each raw stream can contain private prompts, tool arguments, output, file paths, bearer tokens and proprietary target data. Never put raw streams into public CI, public logs, public GitHub issues or model context. Use only approved synthetic fixtures in public CI. In a private deployed workcell, keep raw evidence local/encrypted under the owning classification, short retention and independent credential hygiene controls. This projection emits only allowlisted event counters, a source digest and fixed-vocabulary status; it cannot detect every indirect information disclosure (e.g., event-count side channels). Apply normal disclosure review before any private-to-public projection.

**Epistemic limit:** `session.execution.succeeded` is a *self-reported OpenCode execution marker*, not independent product correctness, behavioral fidelity, sandbox enforcement, complete sensor provenance, or successful GitHub reconciliation. The stream may be partial or omit events (live SSE has no replay guarantee in this adapter), and the session ID is itself unauthenticated. Every summary therefore hardcodes `promotion_allowed=false`, `independent_verifier=NOT_RUN_BY_THIS_TOOL`, and `stream_completeness=UNKNOWN_NO_REPLAY_OR_SEQUENCE_PROOF`. This summary must not be treated as a valid `qualification/run-receipt.schema.json` receipt, must not be imported into an actor qualification decision without an externally owned run/fixture/validator binding, and must never override validator results.

## Follow-on integration gates

1. **Substrate/HIL** (IaC): pin OpenCode V2, capture actual event stream in Hyper-V/WSL2 disposable CoW guest on sovereign local models; verify event shapes, independent session identity and clean termination. No implicit public egress or personal host credentials.
2. **Science** (Spelunker #139): attach a digest-referenced advisory projection to the existing task receipt through an explicitly reviewed adapter (no receipt-schema churn without demonstrated need); compare fixed tasks, models and servers with external validators.
3. **Observatory** (ghidra-tools #4): join internal events to independent process/VM/Ghidra/trace evidence through time-domain, module, run and artifact identity, retaining unknown and contradiction states. This candidate itself does not provide containment or tool actuation.
4. **Private Foundry** (#7/#37): retain confidential task-conditioned fit, positive/negative results and selection policy. Public Foundry receives only reusable, rights-cleared, independently verified model/checkpoint artifact identity, **not** ordinary coding-agent telemetry or private rankings.
5. **Agent Dispatch** (#104): admit task-conditional model/harness/routing decisions only after hard capability, authority, cost and independent-validation gates. Continue to preserve negative/unknown outcomes.

Initial target is a two-model, same-task comparison using existing Model Spelunker tasks and a disposable source-known workcell. Metrics are independently validated task success, retries/turns, false claims, resource utilization, convergence to accepted change, recovery overhead, and per-task resource cost. No self-training or RL update is accepted without held-out comparison, exact configuration identity and rollback.
