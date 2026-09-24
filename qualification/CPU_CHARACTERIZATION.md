# CPU performance-envelope characterization v1

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
