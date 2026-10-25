# Calibration and Blind-Recovery Strategy

## Purpose

Model Spelunker must be evaluated as an instrument system, not merely demonstrated on interesting examples. The calibration program measures whether the combined toolbox can recover known properties, distinguish absent properties, predict unseen behavior, and avoid overstating evidence.

## Three calibration classes

### C1 — Synthetic/model-organism calibration

Use small models or constructed systems where important mechanisms are deliberately known or planted.

Examples:

- finite-state behaviors with hidden states
- synthetic concept classifiers with controlled latent factors
- tiny transformers trained on known algorithms
- models with planted features/circuits
- controlled backdoors/triggers known only to the evaluator
- models with deliberately redundant or misleading correlates

Goal: measure true-positive recovery, false localization, causal fidelity, and uncertainty calibration against a known ground truth.

### C2 — Blind characterization

The inspection team receives only the allowed interface/access tier and does not know training task, planted mechanism, special triggers, or intended capabilities. A separate evaluator holds the answer key.

The team produces a frozen Characterization Package before unblinding.

Score:

- recovered capabilities and missing capabilities
- recovered semantic distinctions
- discovered triggers/state/protocol dependencies
- behavioral prediction on hidden challenge probes
- localization accuracy where ground truth exists
- causal recovery where interventions are possible
- unsupported claims/false discoveries

This is the strongest direct test of whether the SOP can recover meaning rather than explain retrospectively.

### C3 — Natural-model field characterization

Apply the same SOP to real open models where full ground truth is unavailable. Compare against documented training/eval information only after a blind phase, then use independent benchmarks, model-family comparisons, and cross-method agreement/disagreement as secondary validation.

This tests ecological usefulness but must not be confused with known-ground-truth validation.

## Method ablation

Run the same blind-recovery task with subsets of the instrument portfolio:

- behavioral only
- behavioral + fMRI cartography
- behavioral + geometry
- behavioral + probes
- behavioral + sparse features
- behavioral + attribution
- behavioral + intervention
- full portfolio

Measure incremental gain over the cheaper baseline. This answers the operational question: **what additional model understanding did this instrument buy us?**

## Primary calibration outcomes

1. **Held-out behavioral prediction** — accuracy/calibration when predicting unseen responses or capability boundaries.
2. **Semantic recovery** — agreement between recovered concept/relationship structure and planted ground truth.
3. **Boundary recovery** — distance between inferred and true capability/failure frontiers.
4. **State recovery** — similarity of inferred interaction-state model to the planted system.
5. **Localization precision/recall** — where known internal causes exist.
6. **Interventional fidelity** — whether predicted effects of interventions match observed effects.
7. **False-discovery rate** — confident claims unsupported by ground truth.
8. **Query/compute efficiency** — evidence gained per probe/GPU-hour/storage unit.
9. **Analyst burden** — human time required to produce trustworthy conclusions.
10. **Cross-model portability** — whether the method remains useful across architectures, sizes, modalities, and training regimes.

## Golden rule

A method does not graduate into the preferred SOP merely because it finds interpretable-looking structure. It should demonstrate at least one of:

- improved held-out prediction
- improved known-ground-truth recovery
- improved causal fidelity
- materially lower cost for equivalent recovery
- unique detection of important capabilities/failures missed by other instruments

## Red-team cases

Calibration models should deliberately include traps:

- strong correlation without causal use
- distributed mechanisms that defeat single-location narratives
- redundant causal pathways
- polysemantic/superposed features
- protocol-sensitive behavior
- rare triggers
- deceptive decoder priors
- train/test leakage opportunities
- apparent clusters unrelated to function
- activation changes caused by length/tokenization rather than meaning
- interventions that create OOD states
- stochastic or hidden-state-dependent behavior

The SOP must record when it cannot disambiguate these cases.

## Evidence levels

Every calibration result and operational claim uses explicit evidence labels:

- `OBSERVED`
- `REPRODUCED`
- `RELATIONAL`
- `PREDICTIVE`
- `CAUSAL`
- `FUNCTIONALLY_RECOVERED`

A claim may also carry orthogonal tags such as `LOCALIZED`, `DECODED`, `SPARSE_FEATURE`, or `CIRCUIT_HYPOTHESIS`; these tags do not imply a higher evidence level.

## Promotion criteria

An instrument/TTP may move from experimental to standard only after:

1. reproducible execution on at least one C1 suite;
2. useful incremental recovery in a blinded C2 evaluation;
3. known failure modes documented;
4. evidence outputs conform to the common schema;
5. cost/benefit compared with at least one simpler alternative;
6. a falsification or negative-control procedure exists.

This creates a living SOP whose components earn their place through measured recovery value.
