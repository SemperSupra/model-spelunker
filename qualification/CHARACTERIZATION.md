# Unified configured-actor performance-envelope characterization

This is the common scientific method for Model Spelunker qualification/interviews.
CPU, GPU/accelerator, hosted API, router, mobile/embodied, speech/audio, vision/media,
native-build, and future sovereign/GARM lanes use this method and add only the
measurements their execution physics require.

The empirical unit is:

```text
configured actor realization
x deployment / execution environment
x task or workload instance
-> immutable observation
-> task-conditioned performance envelope
-> KSA evidence
-> downstream placement eligibility
```

A configured actor realization includes every material behavior-affecting component:
model/artifact or hosted treatment, inference/generation runtime, harness/framework,
configuration and budgets, context/reasoning strategy, tools/sensors/actuators,
authority, deployment topology/transport, and substrate/resource environment.

## Scientific contract

Every v2 characterization experiment is declared before execution and binds:

- decision question and claim type;
- experimental role: screening, control, boundary, replicate, holdout,
  drift-sentinel, or operational;
- exact actor/task/substrate identities;
- factor(s) under test and frozen factors;
- primary responses;
- stopping conditions;
- invalidation/exclusion conditions.

Raw run receipts are immutable. Derived envelopes are recomputable. A material
configuration or deployment change is a distinct configured-actor treatment.

## Reference and operational science

Use both lanes, but never pool them merely to increase N.

**Reference / causal lane** keeps the smallest useful calibration set:
- one deterministic/easy control;
- one known near-boundary point when established;
- causal one/few-factor treatments that distinguish mechanisms.

**Operational lane** harvests useful real work when the actor-visible packet,
authority, and independent validator can be frozen prospectively. If useful work
cannot form a valid experiment, do the work and do not call it qualification evidence.

## Outcome and censoring semantics

Separate:
- semantic success;
- semantic failure after valid execution;
- right-censored time/resource boundary after work actually started;
- incomplete ingress/runtime/provider execution;
- invalid task/verifier/methodology;
- authority or protocol incompatibility.

For model-backed actors, model calls started are distinct from completed rounds.
The same start/progress/completion distinction should be exposed by other generators
and actuators when their runtimes permit it.

A timeout after real execution begins is performance-envelope evidence, not
automatically a semantic actor failure. A task packaging defect, validator error,
or execution-plane failure never becomes negative actor/KSA evidence.

## Resource and deployment envelope

Record cheap observed facts that can affect placement:
- effective CPU/RAM exposure;
- OS/ISA;
- accelerator/backend identity when material;
- task wall/resource budgets;
- runtime/provider path;
- deployment topology and transport;
- authority/data boundary.

Do not turn every run into a profiler. Add deeper measurements only when an
observed boundary makes that mechanism decision-relevant.

Procedures may transfer across environments; hardware performance claims do not.
A GHA-to-GARM/sovereign crossover mints a new environment realization even when
the task, actor implementation, and validation procedure are otherwise unchanged.

## Task demand and KSA evidence

Qualitative task `demands` are descriptors/strata, not a universal difficulty score.
A task family may add measurable factors such as source bytes, files touched,
subgoals, tool transitions, protected spans, utterance duration, image resolution,
or recovery events when those factors are actually under study.

New task profiles may declare sparse KSA requirements with evidence roles:

- `isolating`: the task/treatment is designed so its outcome can discriminate this KSA;
- `composite`: the KSA is required, but failure cannot localize blame to it;
- `supporting`: the observation contributes positive evidence but is not sufficient
  for a negative KSA conclusion.

A valid PASS may strengthen positive evidence for every required KSA within the tested
conditions. A FAIL on a composite/supporting task is a task-envelope negative only.
Negative KSA evidence requires an isolating task, controlled ablation/crossover, or
another explicit evidence predicate.

Legacy task-class KSA mappings are treated conservatively as composite evidence.

## Adaptive interview loop

Do not precompute an exhaustive Cartesian matrix. After each interpretable observation,
choose the smallest next treatment capable of changing a placement/resource/KSA decision.

Examples:
- output/token ceiling reached -> bounded output-budget treatment;
- iteration ceiling reached while useful progress continues -> iteration treatment;
- reasoning succeeds but actuation blocks progress -> tool-projection crossover;
- fast semantic failure with spare resources -> model/harness/representation/tool
  discriminator, not more CPU/time;
- time/resource censoring -> resource/runtime treatment only when operationally relevant;
- composite failure -> simpler isolating task if KSA localization matters;
- feasible region established -> held-out task or reliability replicate only if the
  delegation consequence needs it.

Stop an axis when another rep is unlikely to change a decision.

## Sampling and uncertainty

Keep these distinct:
- one valid PASS: feasibility observation;
- same-instance repeats: stochastic repeatability;
- distinct task instances: task-family generalization;
- environment repeats: portability/robustness;
- held-out tasks: confirmation after treatment selection.

Do not pool censored/incomplete runs into semantic reliability. For binary semantic
trials, Wilson intervals are acceptable while sample sizes remain small and no stronger
task-family model has earned its keep.

## Measurement planes

Compare outcome/behavior first.

Preserve tokenizer-independent representation volume and wall time for controlled
comparisons, plus provider-native tokens/cache/cost for provider-local accounting.
Do not create cross-tokenizer tokens-per-second rankings.

Domain-specific evidence should be carried through typed, digest-bound extensions
rather than expanding the core receipt with every modality. Candidate extension kinds
include reasoning/runtime, accelerator, embodied/mobile, audio/TTS, image/video, and
native-build evidence.

## Downstream placement

Model Spelunker characterizes. Agent Dispatch places.

The placement consumer should receive an evidence-backed employment profile:

```text
actor realization
+ eligible task/KSA region
+ deployment/resource conditions
+ reliability/uncertainty
+ known boundaries
+ evidence references
+ UNKNOWN outside observed space
```

There is no universal actor score or permanent bare-model qualification label.

## Kill rules

Stop or pause when:
- another run cannot change a decision;
- the validator or task package is uncertain/invalid;
- confirmation data leaked into treatment selection;
- multiple uncontrolled factors changed and causal attribution is being claimed;
- a deterministic measurement already answers the question;
- a factor is demonstrably nonlimiting in the region of interest.

Every experiment must earn its keep by accomplishing useful work, improving a
placement/resource decision, locating a meaningful boundary, resolving attribution,
or qualifying a procedure required by an upcoming deployment.

## CPU lineage

The first implemented performance-envelope tranche was CPU characterization.
`CPU_CHARACTERIZATION.md` remains the execution ledger and worked example for:
reference + operational lanes, resource observation, right-censored in-flight timeouts,
factor-effect experiments, Wilson uncertainty, adaptive stopping, and portability.
Those semantics are inherited here; they are not replaced.
