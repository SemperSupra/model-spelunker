# Multilingual Concept Geometry & Training Dynamics

## Purpose

Evaluate how concepts are represented, separated, associated, and developed inside language models across languages, while distinguishing genuine model structure from prompt, tokenizer, corpus-frequency, and post-training artifacts.

This lane treats **neuralese** as a falsifiable hypothesis about partially language-independent internal representation, not as an assumed hidden language.

## Core research questions

1. Do semantically equivalent concepts expressed through different languages converge toward shared internal representations?
2. Where do language-specific components persist?
3. Can we detect systematic asymmetries in a concept's local geometry that are consistent with training effects?
4. Can causal interventions show that observed concept structure actually influences behavior?
5. When checkpoint-rich models are available, when does concept structure emerge during training?
6. Can training-data attribution connect the emergence or deformation of a concept to specific data populations?
7. Can validated findings improve input construction without collapsing the research into ordinary prompt optimization?

## Concept sampling model

Do not force each concept onto a single positive/negative axis. For each concept `C`, construct four populations:

- **P — positive exemplars:** canonical examples, synonyms, culturally native formulations, prototypical cases.
- **N — negative / contrastive exemplars:** antonyms, explicit non-examples, contradictions, neighboring concepts that should remain distinct.
- **B — boundary cases:** ambiguous, counterfactual, near-miss, context-dependent, and adversarial examples.
- **D — discovery space:** intentionally unlabeled neighboring concepts and multilingual formulations used to reveal geometry we did not pre-specify.

`D` replaces the earlier term "latent/white space" for input sampling. "Latent" is reserved for internal model representations.

## Multilingual generation

For each concept, generate matched probe families across languages and formulations:

- direct native-language expression
- literal translation
- native/culturally adapted formulation
- concise definition
- exemplar
- counterexample
- analogy
- contrastive pair
- semantic decomposition / primitive-style explanation
- mixed-language formulation
- paraphrase ensemble

Record provenance for every probe, including source language, translation path, generation method, and concept relation.

## Threat model / red-team controls

A result must be treated as provisional if it can be explained by:

- tokenization differences
- prompt wording or length
- translation mismatch
- language-resource imbalance
- corpus frequency
- output-language effects
- instruction tuning / post-training effects
- probe leakage
- classifier overfitting
- visualization artifacts
- SAE decomposition artifacts
- off-manifold steering
- multiple-testing effects

Use matched controls and negative controls wherever possible.

## Observer ladder

Use multiple independent observers rather than treating any one interpretability method as ground truth.

### Stage A — behavioral screen

CPU-friendly, broad, cheap.

Measure:

- task accuracy / correctness where ground truth exists
- consistency across paraphrases
- cross-language agreement
- calibration where available
- response entropy / diversity
- token count and latency
- sensitivity to P/N/B/D perturbations

### Stage B — representational screen

For promoted cases only:

- raw hidden-state geometry
- linear probes / concept activation directions
- representation similarity
- clustering / neighborhood analysis
- layerwise convergence across languages
- simple erasure / ablation tests where practical

### Stage C — causal validation

For strong signals:

- activation patching
- causal tracing
- concept erasure
- distributed alignment / causal abstraction methods
- steering with explicit off-manifold checks

### Stage D — developmental validation

For checkpoint-rich model families:

- track concept geometry across checkpoints
- identify first appearance, stabilization, splitting, collapse, or reorientation
- distinguish pretraining effects from later post-training effects

### Stage E — training-data attribution

Only after a representation is stable and causally relevant:

- data attribution / influence methods
- concept-level attribution
- compare attributed examples or domains with observed developmental changes
- require counterfactual retraining or controlled data edits where feasible before making strong causal training claims

## Evidence grades

- **G0 — behavioral anomaly:** effect appears in outputs only.
- **G1 — representational association:** internal structure correlates with the effect.
- **G2 — causal representation:** intervention on the representation changes behavior as predicted.
- **G3 — developmental evidence:** effect can be tracked across training checkpoints.
- **G4 — training attribution:** specific data populations are linked to development of the effect.
- **G5 — counterfactual training validation:** changing/removing attributed data predictably changes the learned concept geometry.

Do not call an effect a "training bias" at G0-G2 without qualification.

## Geometry hypotheses

Permit the evidence to choose among:

- single direction
- multidimensional subspace
- multiple clusters / prototypes
- nonlinear manifold
- overlapping concepts
- language-specific subspaces
- shared cross-lingual core plus language-specific residuals

The test harness should never assume a single-axis representation by default.

## MVP

The MVP is behavioral and CPU-only.

1. Select a small set of open-weight CPU-capable models.
2. Select 10-20 concepts with strong multilingual lexical or cultural variation.
3. Build P/N/B/D probe sets in several languages.
4. Run matched prompt families and record raw outputs plus metadata.
5. Compute behavioral consistency, language sensitivity, boundary sensitivity, and tokenization covariates.
6. Promote only reproducible anomalies into representational experiments.

### Promotion criteria

A concept/model pair is promoted when the observed effect:

- repeats across paraphrases,
- survives prompt-order randomization,
- is not explained by token count alone,
- appears in at least two independently generated probe families,
- has a meaningful cross-language or boundary-space delta,
- survives held-out probes.

## Relationship to prompt optimization

Prompt optimization is downstream, not the first objective.

Research order:

`observe -> map -> falsify -> perturb -> attribute -> optimize`

Only after a concept effect is validated should the system search for tuned multilingual inputs that deliberately activate the useful internal region.

## Data record

Each run should emit a machine-readable Concept Geometry Record containing at minimum:

```yaml
concept_id: string
concept_version: string
model:
  artifact_id: string
  revision: string
  tokenizer_revision: string
probe:
  probe_id: string
  class: P|N|B|D
  language: string
  formulation_type: string
  source: string
  translation_path: string|null
run:
  seed: integer
  prompt_template_version: string
  input_tokens: integer
  output_tokens: integer
behavior:
  raw_output_ref: string
  score: number|null
  consistency_group: string|null
representation:
  observer: string|null
  layer: integer|null
  artifact_ref: string|null
evidence_grade: G0|G1|G2|G3|G4|G5
```

Large model artifacts remain registered through Model Foundry rather than committed into this repository.

## Design rule

Every added observer, model, metric, language, and governance mechanism must earn its keep by improving falsification power, coverage, reproducibility, or cost-efficiency.
