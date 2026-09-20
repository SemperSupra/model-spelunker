# Configured-actor qualification

Issue #54 extends the existing Model Spelunker substitution pattern from model-only
comparisons to configured actors.

The unit under test is:

`task × harness × build × model × configuration × toolset × substrate`

This directory deliberately defines only the experiment-side contract:

- task packages are harness-neutral;
- each stochastic rep emits a new immutable run receipt;
- one-variable crossover reps isolate harness, model, or substrate effects;
- deterministic final-state verification is preferred;
- performance envelopes are derived from receipts; there is no universal winner score.

Substrate construction is external. Receipts reference the exact worker profile and
infrastructure revision used for the rep. Model Artifact Foundry identity is used
when a model artifact is under portfolio control.

## Minimal task package

A task directory contains:

- `task.json` — instruction, fixture, limits, and verifier entry point;
- `fixture/` — initial task state;
- the verifier named by `task.json`.

The verifier must support a self-test that demonstrates at least one known-good
and one known-bad outcome before the task is used for placement decisions.

## First task

`tasks/text-repair-v0` is intentionally trivial. It exists only to prove that
multiple harness/model combinations can receive identical task semantics and
produce comparable receipts. It is not a meaningful coding benchmark.

Do not add a scheduler, database, dashboard, agent registry, or new execution
service here. Agent Dispatch remains the execution/routing authority and the
infrastructure repository owns worker substrate construction.

## Failure observations

The terminal `failure_class` stays deliberately small:

- `timeout` — the candidate exceeded the task wall clock;
- `candidate-error` — the candidate process exited non-zero;
- `false-completion` — the candidate exited zero but deterministic verification failed.

A timeout does not erase evidence about what happened before the wall clock expired.
Receipts may also include `failure_signals` such as invalid tool use, approval/authority
mismatch, sandbox-helper failure, hosted-runner user-namespace failure, or repeated
tool-recovery failures. These signals are evidence annotations, not a replacement
for deterministic verification.

`timed_out` and `state_changed` are recorded separately so downstream placement
logic can distinguish, for example, a slow actor that made progress from one that
timed out without changing task state.

For expensive model-backed reps, validate the harness execution substrate before
model hydration whenever a cheap no-model preflight exists. A broken sandbox or
runtime is a substrate observation and should not consume model inference time.

## Build provenance

For open-source harnesses, the compiled/package projection is part of the configured
actor when it can change startup cost or the runtime/model-facing capability surface.

Receipts may therefore preserve a small optional `candidate.build` block containing
the source revision, build profile, toolchain, default-feature decision, selected
features, and final artifact digest. The complete candidate metadata still contributes
to `configuration_digest`.

Do not expand compiler flags into an experiment matrix unless an observed bottleneck
makes them relevant. Prefer structural projections that remove unused providers,
telemetry, voice, UI, plugins, or other capability surfaces over micro-optimizing
code generation.

## Hosted API model treatments

Hosted API models are valid model treatments alongside sovereign/local CPU or GPU
models when the harness, task, tool projection, substrate, and authority envelope can
otherwise be held constant.

API-backed qualification workflows are manual-only and must:

- receive provider credentials only at execution time from an external secret store;
- never serialize credential values into candidate metadata, receipts, diagnostics, or artifacts;
- run a non-inference authentication/readiness preflight when the provider exposes one;
- preserve the provider/model alias and the date or contract revision used for interpretation;
- record provider-reported token usage when available;
- keep `cost` null unless an exact, contemporaneous billing calculation is independently
  derived from provider usage and pricing evidence.

Provider aliases are not immutable model artifacts. A receipt for a hosted alias such
as `deepseek-flash` proves behavior of the provider-served configured actor at that
time; it does not claim possession of an immutable model checkpoint.

### Free-tier hosted providers

Hosted free-tier/free-variant providers are model treatments, not harnesses.

Current initial catalog:
- Groq: `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`;
- OpenRouter: specific `:free` model variants;
- OpenRouter `openrouter/free`: router treatment only, never interpreted as one model.

For Groq, free access is an account-tier property. A models preflight proves that the
key can access the requested model, but it cannot prove that the account has not been
upgraded to a paid tier. Keep these runs manual and bounded.

For OpenRouter, a specific model qualification MUST use an explicit `:free` variant
when the treatment is intended to be zero-token-price. `openrouter/free` randomly
routes among eligible free models and therefore qualifies the router behavior rather
than a stable model identity.

The free-provider roster is intentionally small. Add candidates only when they support
the task's required capabilities and produce useful coverage rather than enumerating
every free endpoint.

## Cross-model measurement semantics

Provider-native tokens are retained because they matter for quotas, billing, caching,
and model-local throughput. They are **not** treated as a universal unit of semantic
work across model families or providers.

Qualification therefore preserves several measurement planes:

1. **Outcome / behavior**
   - deterministic verifier result;
   - state change;
   - tool calls, approvals, retries, failure signals, model rounds.

2. **Tokenizer-independent workload**
   - serialized message bytes presented to the harness provider;
   - serialized tool-schema bytes;
   - output text bytes;
   - reasoning bytes;
   - tool-argument bytes.

3. **Provider-native accounting**
   - prompt/input tokens;
   - completion/output tokens;
   - cache read/write tokens;
   - provider reasoning/native tokens when exposed;
   - exact provider cost when exposed.

4. **Time / capacity**
   - client-observed model-call wall time;
   - time to first streamed event;
   - provider queue/prompt/completion/total time where exposed;
   - rate-limit/quota observations where available.

5. **Identity / routing**
   - requested model/provider;
   - resolved model returned by the service;
   - backend/system fingerprint where exposed;
   - serving provider and router metadata where exposed;
   - service tier and generation/request identifiers.

Do not rank models by raw tokens/second across tokenizers. Compare task success and
behavior first, then use byte-normalized and wall-time measures for cross-model
efficiency. Provider-native tokens remain essential within a provider/model accounting
regime.

For OpenRouter, the adapter may enrich completed generations through the metadata-only
`/api/v1/generation` endpoint. This records the actual routed model/provider and
native token/timing/cost information without retrieving stored prompt/completion
content.

