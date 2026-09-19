# Configured-actor qualification

Issue #54 extends the existing Model Spelunker substitution pattern from model-only
comparisons to configured actors.

The unit under test is:

`task × harness × model × configuration × toolset × substrate`

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
