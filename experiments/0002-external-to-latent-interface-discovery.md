# Experiment 0002 — External-to-Latent Interface Discovery

## Goal

Test whether semantically equivalent external representations map into an internal representation that is not merely decodable but **causally addressable and reusable**.

The experiment is successful only if we can move beyond correlation toward a practical map:

`external representation -> latent state -> downstream function`

## Research object

A candidate latent representation may be a direction, multidimensional subspace, prototype family, polytope, manifold, or workspace-like pattern. Do not assume a single vector in advance.

## First target

Use a deliberately small concept set to validate the apparatus before broadening:

- reciprocity
- one concrete-category control
- one simple relational/function control

Use the existing matched English/German/Thai probe infrastructure first. Add languages only after the hidden-state path is validated.

## Model sequence

### Plumbing model

Start with a checkpoint-rich small open model already integrated into the public CPU path, e.g. Pythia-70m, solely to validate capture, provenance, and analysis.

### Promotion model

If the apparatus works, move to a stronger but still tractable open-weight model where multilingual representation is meaningful. Model Foundry must bind exact weights/tokenizer/revision before results are compared.

Do not interpret a null result from the plumbing model as evidence against the general hypothesis.

## Probe requirements

For each semantic item preserve:

- concept identity independent of language surface
- positive/negative/boundary/discovery class where applicable
- language and translation path
- independent paraphrase family
- tokenizer statistics
- exact text and tokenization

Behavioral success is not required for the probe to be useful. Semantic equivalence quality is the main requirement.

## Capture plan

For every probe capture hidden states across all transformer layers at multiple readout positions:

1. final prompt token
2. mean-pooled prompt span
3. concept-bearing span when a defensible alignment exists
4. optional attention/MLP residual points if cheap enough

Store compact derived features in CI artifacts. Full activation tensors should remain ephemeral or be separately registered if retained.

## Adopted observer: Jacobian lens / J-space

Do not build a bespoke latent decoder before testing the strongest available reusable primitive.

Adopt the reference implementation at `anthropics/jacobian-lens`, pinned to upstream commit:

`581d398613e5602a5af361e1c34d3a92ea82ba8e`

License: Apache-2.0.

The Jacobian lens linearly transports an intermediate residual-stream vector into the final-layer basis using an average input-output Jacobian, then decodes through the model's own unembedding. This makes it an independent observer from our mean-difference / probe family and directly supports the J-space/global-workspace hypothesis.

Use it as an observer, not as ground truth. Compare its readouts against:

- raw activation geometry
- held-out linear/counterfactual directions
- representation-similarity/alignment methods
- causal write/erase/patch interventions

For first integration, fit a small lens on a plumbing model with a bounded generic-text sample. Do not widen fitting data until the observer produces stable, reproducible artifacts. The upstream reference notes that ~100 fitting prompts can be usable even though the paper used a larger corpus.

The first strong J-space-style replication target is not merely readable vocabulary. It is a representation that survives a **read -> write -> reuse** sequence across more than one downstream function.

## Adopted causal calibration: released probe-swap

Before inventing a new causal-write benchmark, reproduce the released J-space probe-swap protocol.

Pinned upstream source:

- repository: `anthropics/jacobian-lens`
- commit: `581d398613e5602a5af361e1c34d3a92ea82ba8e`
- data: `data/experiments/probe-swap.json`
- released item count: 90 two-hop prompts

Do not vendor or hand-copy the published dataset unless a future availability problem earns that duplication. The CPU harness downloads the exact raw file from the immutable upstream commit, records its SHA-256, and stores that provenance with the result.

### Intervention primitive

For source concept token `s`, replacement concept token `t`, and layer `l`, use the released two-coordinate J-lens swap:

`v_s = J_l^T w_s`

`v_t = J_l^T w_t`

`V = [v_s, v_t]`

`c = V^+ h`

`h' = h + alpha * V * (swap(c) - c)`

where `V^+` is the pseudoinverse and `swap(c)` exchanges only the source and target coordinates.

This edits only the 2-D span of the two J-lens directions; the remainder of the residual vector is left unchanged. Apply the hook at every prompt-token position in each selected layer, matching the released demonstration.

### Calibration metrics

Keep the paper-faithful result and one weaker diagnostic separate:

1. **causal top-1 success** — clean greedy next token is the published `answer`, while the intervened greedy next token is the published `swap_answer`;
2. **preference flip** — clean logits prefer `answer` over `swap_answer`, while the intervention reverses that pairwise preference.

A preference flip is evidence of directional causal influence but does not count as the stronger top-1 swap result.

### Minimal red-team controls

The plumbing-model calibration adds only controls that directly falsify common artifacts:

- strength sweep (`alpha` = 0.5, 1.0, 2.0 initially);
- early-half versus late-half fitted-layer ablations;
- clean no-intervention baseline;
- single-token eligibility accounting and explicit skips;
- baseline-answer correctness and baseline pairwise preference denominators.

For Pythia-70m the primary apparatus condition is `all_fitted` layers. Do **not** call this a discovered workspace band. The early/late split is an ablation control only. If causal effects survive, a model-specific workspace-band search can be earned later.

### Calibration promotion rule

The released probe-swap apparatus is considered operational when it produces reproducible causal effects on at least some baseline-correct items and those effects show layer and/or strength structure distinguishable from the ablations. No fixed success-rate threshold is invented in advance for the plumbing model.

A null result on Pythia-70m means the plumbing model or intervention/model pairing is insufficient; it does not falsify the broader latent-interface hypothesis. Promotion then requires a stronger open model with an available fitted lens before bespoke representation machinery is considered.

## Phase A — read / convergence

Questions:

- Are same-concept examples closer than different-concept controls after surface-form controls?
- Does cross-language convergence increase at particular layers?
- Is there a shared core plus language-specific residual?
- Does a simple direction suffice, or does a higher-dimensional representation materially improve held-out decoding?

Methods, in increasing complexity:

1. normalized activation differences
2. linear probes / counterfactual directions
3. representational similarity
4. CCA / orthogonal Procrustes alignment across languages
5. Jacobian-lens / J-space readout as an independent observer
6. prototype / subspace models
7. nonlinear manifold analysis only if simpler hypotheses fail

All models are fit on training probe families and evaluated on held-out semantic items and paraphrases.

## Phase B — write / causal addressability

A candidate representation earns promotion only if an intervention changes downstream behavior predictably.

Interventions:

- add / subtract representation
- activation replacement
- activation patching from a matched source prompt
- concept erasure / projection removal

Controls:

- random direction matched in norm
- unrelated-concept direction
- layer-shift control
- token-position-shift control
- sign reversal
- dose-response sweep

## Phase C — cross-language transfer

Strong test:

1. derive a candidate representation only from English probes;
2. intervene while the model processes German or Thai prompts;
3. measure whether the predicted semantic effect transfers;
4. reverse source/target languages.

A shared latent representation should transfer more reliably than language-specific artifacts.

## Phase D — task reuse

Test whether one representation can feed multiple downstream computations.

For a concept such as a country/entity, one latent write should be usable by several tasks such as category, associated property, relation, or retrieval. For abstract concepts use distinct downstream judgments that require the same semantic state.

Do not retrain a separate representation per downstream task for this test.

## Phase E — composition

Only after read/write/reuse succeed:

- add two concept representations
- subtract/negate a representation
- compose concept + relation or function + argument
- test order sensitivity

The goal is to determine whether anything resembling reusable latent operators exists, not to force vector arithmetic to work.

## Phase F — inverse external-code search

This is the practical Neuralese-input objective.

Given a validated target latent state `z*`, search external input space for a compact input `e` such that:

`h_l(e) ~= z*`

while preserving causal downstream behavior.

Candidate external codes may be:

- ordinary natural-language paraphrases
- multilingual mixtures
- semantic decompositions
- symbols / structured text
- learned soft prompts where permitted

Optimize only after causal validation. The objective is **robust addressability per unit input cost**, not strange-looking prompts for their own sake.

## Primary evidence outputs

For each candidate representation record:

- model/revision/tokenizer
- layer and readout position
- training probe IDs
- held-out probe IDs
- representation type and dimensionality
- readout performance
- within/between concept separation
- cross-language transfer result
- intervention effect size and dose curve
- random/unrelated-direction controls
- downstream task reuse result
- composition result if attempted
- external-code efficiency if attempted
- evidence grade

## Promotion gate

A candidate reaches "addressable Neuralese" status only after all of the following:

1. held-out readout above matched controls;
2. paraphrase robustness;
3. at least one cross-language test;
4. causal write or erase effect;
5. random-direction and layer/position controls fail to reproduce the effect;
6. the representation works in at least two downstream contexts.

Composition and compact external-code discovery are later promotion stages.

## Failure is informative

Important falsification outcomes include:

- representations are easily decoded but cannot be causally written;
- cross-language similarity is entirely explained by token/lexical structure;
- each downstream task requires a different representation;
- candidate concept vectors collapse under held-out paraphrases;
- interventions only work at unnatural magnitudes or off-manifold states;
- external prompt search improves behavior without converging on the hypothesized latent state.

These outcomes constrain what we are justified in calling Neuralese.
