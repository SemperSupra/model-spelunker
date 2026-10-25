# Model Spelunker Integration with Agent Qualification

## Objective

Model Spelunker must work consistently for three execution modes:

1. human analyst
2. deterministic automation
3. autonomous/semi-autonomous agent

The same probe definitions, evidence contracts, claim levels, provenance, and qualification outputs should be usable in all three modes. Human interfaces may be richer, and agents may perform adaptive experiment selection, but neither gets a different scientific truth model.

## Qualification target hierarchy

Agent qualification must distinguish at least four layers:

### Q0 — Reasoning-model qualification

Characterize each reasoning model independently where access permits:

- capability/limitation map
- protocol sensitivity
- semantic/concept structure
- stochasticity and decision surfaces
- state/history dependence
- failure modes and blind spots
- internal representations/mechanisms when available

This is the primary Model Spelunker domain.

### Q1 — Agent-framework qualification

Qualify the non-model framework independently where practical:

- planning/control-loop semantics
- tool routing
- memory/context behavior
- retry/recovery
- delegation
- authority enforcement
- prompt/template transformation
- state persistence
- validation/acceptance behavior

Use deterministic or stub models whenever possible to isolate framework behavior from model behavior.

### Q2 — Model × framework composite qualification

Qualify the actual agent composition because behavior may emerge from interactions that neither component exhibits alone.

Key questions:

- Does the framework amplify/suppress model capabilities?
- Does protocol serialization alter model policy?
- Do retries/memory/tool wrappers create new failure modes?
- Are nominally identical models behaviorally different under different frameworks/configurations?
- Which component is responsible for a discovered behavior?

Use differential and component-substitution experiments to attribute effects.

### Q3 — Embodied agent/system qualification

Qualify the complete deployed agent with its tools, credentials, environment, authority envelope, sensors/actuators, network boundaries, and operational workload.

This layer measures mission-level behavior and safety/assurance, but should retain links to Q0-Q2 evidence so failures can be localized rather than treated as opaque system defects.

## Common probe and evidence contract

Every qualification event should consume the same canonical `ProbeCase`/work object and emit interoperable evidence regardless of executor.

```text
ProbeCase
   ↓
Human | Automation | Agent
   ↓
Model / Framework / Composite / Embodied System
   ↓
ObservationBundle(s)
   ↓
Claim/Evidence graph
   ↓
Qualification decision
```

Required invariants:

- same semantic test intent across execution modes
- machine-readable probe specification
- human-readable rendering generated from the same source
- deterministic identifiers for probe, model/framework/configuration, and run
- raw observations preserved separately from derived interpretation
- no executor may promote a claim beyond its evidence level
- human judgment is recorded as evidence/decision, not silently substituted for measurements
- agent-generated hypotheses are proposals until independently supported

## Three interaction surfaces

### Human surface

Optimized for hypothesis formation, exploratory inspection, visualization, annotation, and adjudication.

Humans should be able to:

- author/modify ProbeCases
- inspect raw and derived evidence
- compare instruments and configurations
- annotate hypotheses/alternative explanations
- request falsification or follow-up tests
- accept/reject qualification claims

### Automation surface

Optimized for repeatability and qualification at scale.

Automation should be able to:

- execute fixed test suites
- replay known probes
- compute metrics/statistics
- run conformance vectors
- compare against thresholds/baselines
- package reproducible evidence

This is the preferred surface for regression qualification.

### Agent surface

Optimized for adaptive exploration where fixed suites are insufficient.

Agents may:

- propose hypotheses
- select discriminating follow-up probes
- perform prior-art/method selection
- search for counterexamples
- choose instruments based on expected information gain
- summarize contradictions and uncertainty

Agent autonomy does not remove independent validation or authority controls.

## Instrument portability

Every Model Spelunker instrument should declare:

- required access tier (A0-A4)
- supported execution modes: human / automation / agent
- required inputs
- produced evidence types
- known failure modes
- determinism/stochasticity expectations
- cost characteristics

An instrument should not have a human-only hidden semantic contract. If a human can use it, the essential inputs/outputs must be expressible in machine-readable form so automation or agents can reproduce the same experiment.

## Agent qualification integration pattern

During agent qualification, do not treat the agent as one undifferentiated black box by default.

Preferred sequence:

1. qualify reasoning model(s) independently where possible;
2. qualify framework/control logic with deterministic substitutes where possible;
3. qualify model-framework composites using component substitution/differential tests;
4. qualify the embodied agent end to end;
5. when an end-to-end anomaly appears, descend the hierarchy to localize the cause;
6. feed recurring model/framework failure signatures back into regression qualification suites.

## Differential decomposition

For a system composed of framework F and model M, maintain controlled substitutions:

```text
F1 + M1
F1 + M2
F2 + M1
F2 + M2
```

Where practical, also include deterministic model stubs and deterministic framework harnesses.

This lets qualification distinguish:

- model-main effects
- framework-main effects
- model × framework interaction effects
- embodiment/environment effects

The objective is causal attribution strong enough to guide remediation and qualification scope, not merely leaderboard scoring.

## Graduation into agent qualification

A Model Spelunker method may be incorporated into the standard agent-qualification suite when it demonstrates one or more of:

- detects material failures missed by existing qualification
- improves attribution/localization of failures
- improves held-out prediction of agent behavior
- provides a cheaper equivalent measurement
- provides a reproducible internal/mechanistic signal that predicts externally relevant behavior

Methods that are informative for exploratory science but add no qualification value may remain research instruments rather than mandatory gates.

## Initial integration milestone

Use the current fMRI/protocol-sensitive model experiments as the first shared rep:

1. define one canonical ProbeCase corpus;
2. run behavior + probability-surface + fMRI/representation methods against the same models;
3. execute the corpus through a minimal agent framework wrapper as well as direct model access;
4. compare direct-model versus framework-mediated results;
5. identify which signals remain stable, which are framework-induced, and which predict composite behavior;
6. package the useful subset as candidate agent-qualification checks.

This creates a direct bridge from Model Spelunker research to practical agent qualification without forcing every research instrument into the production qualification path.