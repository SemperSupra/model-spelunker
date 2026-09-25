# CPU performance-envelope characterization v1

This document is the first execution ledger / worked example of the common
[configured-actor characterization method](CHARACTERIZATION.md). The common
scientific rules live there; CPU-specific observations and experiment history stay
here so the general method does not erase its empirical lineage.

This work extends issue #54 under the configured-actor methodology owned by
`SemperSupra/agent-dispatch-private#104`. It does not create a second benchmark
platform, scheduler, registry, or qualification authority.

## Objective

Characterize useful operating regions for reasoning/generative systems rather than
reducing a configured actor to a universal PASS/FAIL label.

The empirical unit remains:

`task × harness × model × configuration × toolset × substrate × resource/budget envelope`.

Raw run receipts are immutable. Derived envelopes are recomputable.

## Scientific rules

A v2 experiment declaration is written before execution and binds:

- claim type;
- task and configured actor treatments;
- factor under test and frozen factors;
- primary responses;
- experimental role and design block;
- stopping conditions;
- exclusion/invalidation conditions.

Legacy v1 observations remain valid at their original claim boundary. They are not
retroactively upgraded into v2 experiments.

Timeout after one or more model rounds is right-censored performance evidence, not
semantic failure. Zero-model-round timeout remains an incomplete ingress/runtime
observation. Validator errors and invalid task packages never become actor negatives.

Same-instance repeats, environment/block repeats, and distinct task-instance samples
answer different questions and must not be pooled merely to increase N.

For binary semantic outcomes the reducer reports a Wilson 95% interval over actual
semantic trials. A small N remains visibly uncertain; there is no fixed “10 reps =
qualified” rule.

## Two coupled work streams

### A. Reference / causal science

Use frozen historical tasks and exact model artifacts to test whether the methodology
recovers known mechanisms and boundaries. The first block is
`cpu-reference-qwen17-text-repair-v1`.

The historical seed observations include:

- projected OpenWorker + Qwen3 1.7B inside the 120 s text-repair envelope;
- stock/minimized Codex + the same Qwen artifact outside that envelope with prompt
  processing dominating the wall-clock budget;
- Goose/Qwen timeout evidence after actual model inference;
- historical Qwen output/iteration limits showing that hard budgets can masquerade
  as competence failures.

These are design points, not population-level reliability estimates.

### B. Operational science

Harvest evidence from useful work when a real task already has bounded authority,
reproducible inputs, and an independent validator. Do not deform useful work just to
fill a benchmark matrix.

The first prospective work sample is the corrected
`api-boundary-classification-v1` reverse-engineering task. Its v0 predecessor was
invalidated by workspace-layout confounding; v1 is the corrected immutable package.

If a real work item cannot form a valid experiment, do the work and do not call it
qualification evidence.

## Work packages

1. **WP0 scientific contract** — v2 experiment declaration, termination semantics,
   exclusion rules, and resource observation.
2. **WP1 historical CPU census** — inventory canonical receipts and issue/artifact-only
   historical points; preserve UNKNOWN where fields were never measured.
3. **WP2 measurement** — capture cheap CPU/RAM exposure in every v2 run; use
   runtime-native prefill/decode/load telemetry when available. NUMA/perf/RAPL remain
   hypothesis-driven diagnostics, not mandatory overhead.
4. **WP3 reducer** — separate semantic fail, censored timeout, incomplete ingress, and
   validator invalidity; report uncertainty and task-instance counts.
5. **WP4A reference campaign** — calibrate against known Qwen/OpenWorker/Codex/Goose
   boundaries.
6. **WP4B operational campaign** — prospectively qualify current bounded work samples.
7. **WP5 adaptive follow-up** — choose the smallest next treatment that discriminates
   competing explanations; do not retry until PASS.
8. **WP6 confirmation** — repeatability, environment robustness, and held-out task
   generalization are measured separately.
9. **WP7 response surface** — only after a small number of continuous factors earn it.
10. **WP8 Agent Dispatch consumption** — consume derived task-conditioned envelopes,
    never a universal actor score.
11. **WP9 drift sentinels** — retain one control, one near-boundary, and one operational
    point only after a useful envelope has been established.

## Kill rules

Stop or pause when another run no longer changes a decision; the validator becomes
uncertain; confirmation data leaked into configuration selection; multiple uncontrolled
factors changed; a deterministic measurement answers the question; or a factor is
already nonlimiting in the region of interest.

Every experiment must earn its keep either by improving a placement/resource decision,
discovering a hidden limiting factor, preventing a false actor conclusion, or producing
useful operational work.

## Initial execution

The bootstrap deliberately runs two cells with the same admitted OpenWorker/Qwen3 1.7B
CPU actor:

1. reference: `text-repair-v0`;
2. operational: `api-boundary-classification-v1`.

The purpose is not to establish reliability from N=1. It is to prove that the v2
contract produces interpretable scientific receipts while simultaneously exercising a
current reverse-engineering task class. Follow-up treatments are selected only from the
evidence returned by these cells.

## Execution ledger


- **2026-09-24 — bootstrap attempt 1:** invalid for actor science. The two reusable workflow calls shared a branch-only concurrency key, so the operational cell was cancelled by the reference cell. This was an execution-method confound, not actor evidence. The key was corrected to include task and experiment identity before replay.
- **2026-09-24 — bootstrap replay, Actions run 36019670706:** both cells executed independently with the same admitted OpenWorker `5bc10d9` + exact Qwen3 1.7B/Ollama realization.
  - Reference `text-repair-v0`: semantic PASS; 9.419455 s wall; 2 model rounds; 1 tool call; 257 input / 44 output tokens; 4 visible CPUs; ~16.77 GB RAM; AMD EPYC 7763 runner. This is one control observation, not a reliability estimate.
  - Operational `api-boundary-classification-v1`: semantic FAIL (`false-completion`, `state-unchanged`); 15.076346 s wall; 2 model rounds; 1 tool call; 584 input / 126 output tokens; no timeout, engine error, or validator error; 4 visible CPUs; ~16.77 GB RAM; AMD EPYC 9V74 runner.
- **Interpretation:** the operational negative is inside the observed wall-time/resource envelope and terminated voluntarily after real inference. More CPU or a larger timeout is therefore not the earned next treatment. The next discriminator must distinguish configured-actor reasoning/body effects (model, harness/tool realization, or task-facing representation) while keeping the corrected v1 verifier immutable.
- Both v2 receipts are preserved under `qualification/evidence/` and the reducer contract asserts their task-conditioned semantics and Wilson interval behavior.

- **2026-09-24 — adaptive discriminator authorized:** after the operational API-boundary semantic negative terminated in two rounds without exhausting time, CPU, token, or iteration ceilings, the next bounded treatment changes only the OpenWorker reasoning projection from explicit `none` to omitted/provider-default. The corrected task/verifier, exact Qwen3 1.7B artifact, OpenWorker artifact, Ollama version, projected tools, max_tokens=2048, max_iterations=4, authority, and public CPU venue remain frozen. This rep tests a factor effect; it does not claim that omitted projection necessarily enables a particular reasoning mode.

- **2026-09-24 — reasoning-omitted first observation:** 180.092869 s timeout, no state change, and no completed standardized model round. Because the adapter emitted provider observations only after completion, this result cannot distinguish pre-inference failure from an in-flight model call. It is preserved as measurement-limited evidence and is not an actor competence negative.
- **Measurement repair:** the adapter now emits a bounded model-call-start marker containing only call index, requested model id, and serialized request/tool-schema byte counts. The receipt records calls started separately from rounds completed. A timeout with an observed started call is censored performance evidence; a true zero-attempt timeout remains incomplete.
- **Replay authorized:** exact reasoning-omitted treatment replayed only to resolve this attribution gap; actor/task/resource/budget semantics are unchanged.

- **2026-09-24 — reasoning-omitted replay:** 180.097820 s timeout with two model calls observed as started, zero completed standardized rounds, and no state change on 4 visible CPUs (AMD EPYC 7763). This is censored performance evidence, not semantic failure. The same omitted projection had already exhausted 180 s on an EPYC 9V45 before in-flight-call instrumentation was added.
- **Control authorized:** execute one explicit `reasoning_effort=none` control under the same factor-effect experiment declaration. This is the missing control cell, not an attempt to force a PASS.

- **2026-09-24 — explicit-none control:** semantic FAIL (`false-completion`, `state-unchanged`) in 10.310026 s on 4 visible CPUs (AMD EPYC 9V45); 2 model calls started and completed, 1 tool call, 584 input / 119 output tokens, 0 reasoning bytes, no timeout.
- **Factor finding:** explicit `reasoning_effort=none` is inside the tested CPU/time performance envelope but semantically incorrect on this task. Omitting that projection is outside the 180 s performance envelope in two observations (EPYC 9V45 and EPYC 7763); the instrumented replay observed two model calls start and zero complete. The factor materially changes execution cost/latency, but neither treatment establishes task competence.
- **Stop:** no further omitted-reasoning reps are earned for this task. More CPU/time would optimize a treatment already outside the current operational envelope without evidence it improves semantic outcome. Next characterization should change a different plausible limiting dimension while preserving this result.
