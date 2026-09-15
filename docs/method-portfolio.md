# Holistic Model Inspection Method Portfolio

## Mission

Recover a trustworthy, evidence-backed characterization of an unknown or poorly documented model: capabilities, limitations, semantic structure, protocol dependencies, state, failure modes, internal representations, and causal mechanisms where access permits.

No single inspection method is treated as authoritative. Methods are run as complementary instruments against shared probes and are compared for coverage, informativeness, fidelity, cost, robustness, and unique contribution.

## Access tiers

The framework must degrade gracefully according to the access available for the model under test.

| Tier | Available surface | Examples of compatible methods |
|---|---|---|
| A0 | input/output only | behavioral, metamorphic, differential, fuzzing, boundary search, state inference |
| A1 | A0 + token probabilities/logprobs | choice surfaces, entropy/margin maps, counterfactual token scoring |
| A2 | A1 + hidden activations | fMRI-style cartography, geometry/RSA/CKA, learned probes, Patchscopes-like decoding |
| A3 | A2 + weights/gradients | weight analysis, gradient attribution, SAEs/transcoders, attribution/circuit methods |
| A4 | A3 + intervention/mutation | activation patching, ablation, steering, causal mediation, component replacement |

A characterization package must state its access tier so a reader can distinguish evidence that was impossible to collect from evidence that was attempted and failed.

## Instrument lanes

### 1. Behavioral system identification

**Reveals:** capabilities, boundaries, invariances, state dependence, protocol dependence, failure modes.

TTPs include minimal pairs, metamorphic transformations, differential testing, multilingual/concept triangulation, fuzzing, adaptive boundary search, equivalence challenges, state-machine inference, and held-out prediction.

This is the universal baseline because it works at A0.

### 2. Probability-surface inspection

**Reveals:** uncertainty, competing responses, weakly expressed alternatives, decision margins, discontinuities hidden by greedy decoding.

Uses token/logprob trajectories and counterfactual scoring when available. It bridges observed output behavior and latent decision tendencies without claiming internal mechanism.

### 3. fMRI-style activation cartography

**Reveals:** where and when activity changes under controlled stimulus contrasts; distributed activation signatures; layer/token trajectories; candidate regions for deeper inspection.

Treat this as localization and comparative cartography. Activation magnitude or contrast is not automatically a semantic label or causal mechanism.

### 4. Representational geometry

**Reveals:** similarity structure, clustering, separability, invariance, abstraction, and transformations of representations across layers.

Candidate methods include representational similarity analysis, CKA, cosine/subspace comparisons, dimensionality/redundancy measures, and cross-condition alignment.

Useful for determining whether two externally equivalent concepts are represented similarly even when individual activation coordinates differ.

### 5. Learned probes

**Reveals:** whether information is decodable from a representation and at which layers/tokens.

Use simple probes first, strict train/test separation, selectivity controls, randomized-label baselines, capacity controls, and out-of-distribution challenge sets. Decodability is not causal use.

### 6. Vocabulary and natural-language decoding

**Reveals:** human-readable hypotheses about hidden representations and their evolution.

Includes logit/tuned-lens style projection, Patchscopes-style representation inspection, and natural-language activation decoding where practical. Decoder priors and faithfulness failures must be measured rather than assumed away.

### 7. Sparse feature discovery

**Reveals:** candidate recurring features that may be obscured by superposition and can provide reusable units for larger-scale analysis.

Includes SAEs, transcoders, cross-layer transcoders, dictionary learning, and related sparse decomposition methods. Feature labels are hypotheses; reconstruction error, feature splitting/merging, and abstraction-level mismatch are first-class evidence.

### 8. Attribution and circuit reconstruction

**Reveals:** candidate information-flow paths connecting inputs, internal features/components, and outputs.

Includes attribution graphs, path attribution, Jacobian-based lenses, and circuit-localization methods. Explanations must retain reconstruction/fidelity measurements and be validated against interventions when possible.

### 9. Causal intervention

**Reveals:** whether candidate representations/components actually influence behavior under defined interventions.

Includes activation patching, interchange interventions, ablation, steering, causal mediation, component replacement, and counterfactual activation insertion.

Interventions require controls for distribution shift, intervention strength, corruption choice, metric choice, and collateral effects.

### 10. Weight-space and structural inspection

**Reveals:** architectural organization and reusable global structure not tied to a single prompt.

Candidate methods include weight statistics, spectral/subspace analysis, head/MLP similarity, embedding-unembedding relationships, checkpoint/model diffing, and architecture-specific structural diagnostics.

Weights alone do not establish runtime function; they generate hypotheses to test behaviorally and interventionally.

### 11. Longitudinal/model-difference analysis

**Reveals:** what changed across checkpoints, fine-tunes, quantization, adapters, merges, or model families.

Run identical probes and aligned internal measurements across versions. Useful for isolating capability acquisition/loss, representation drift, and post-training effects.

### 12. Cross-modal inspection

For multimodal systems, replicate the same philosophy across image/audio/video/sensor representations and explicitly test cross-modal concept alignment, modality-specific blind spots, and modality routing.

## Shared experiment rule

A `ProbeCase` defines the stimulus, controlled contrasts, expected invariances/changes, task semantics, and metadata once. Every compatible instrument observes that same event.

This enables questions such as:

- Did behavioral output change?
- Did its probability surface change before output changed?
- Where did activation divergence first appear?
- Did geometry separate the conditions?
- Could a probe decode the distinction?
- Did sparse features correspond to the distinction?
- Did a circuit/path attribution connect it to the output?
- Did intervention on that candidate actually alter the behavior?

The conjunction is more informative than any individual result.

## Recovery dimensions

Do not collapse model recovery to one score. Maintain a recovery vector:

1. **Capability coverage** — what tasks/behaviors have been mapped?
2. **Boundary resolution** — how precisely are success/failure frontiers known?
3. **Semantic recovery** — how well are concepts, distinctions, relations, and invariances recovered?
4. **Protocol recovery** — how well are interface/serialization/state dependencies understood?
5. **Predictive fidelity** — can the characterization predict unseen behavior?
6. **Localization fidelity** — can internal loci/times/features associated with behavior be reproduced?
7. **Causal fidelity** — do interventions support claimed mechanisms?
8. **Failure-mode coverage** — are brittleness, deception/artifacts, OOD behavior, and instability mapped?
9. **Uncertainty calibration** — does confidence track actual reliability?
10. **Reproducibility/provenance** — can another operator reconstruct each claim?

## Method comparison scorecard

For each method and model, record:

- access tier required
- wall/compute/storage cost
- query/sample efficiency
- human analyst burden
- automation readiness
- behavioral coverage
- semantic resolution
- spatial/layer localization
- temporal/token localization
- predictive value on held-out probes
- causal evidence strength
- robustness to prompt/protocol changes
- robustness across model families/scales
- reproducibility
- contradictions with other instruments
- unique information beyond the rest of the portfolio

The last metric is crucial. A method that produces attractive results but adds no predictive or explanatory information beyond cheaper methods should not dominate the SOP.

## Evidence fusion

Instrument agreement increases confidence but does not erase common-mode failure. For every important claim retain:

- supporting instruments
- contradicting instruments
- known shared assumptions
- independent controls
- scope/conditions
- confidence
- next falsification probe

The system should actively prefer follow-up experiments that discriminate between competing explanations or resolve cross-instrument disagreement.

## Initial execution order

For cost-effective recovery, default to:

1. A0 behavioral reconnaissance and protocol characterization
2. probability surface if available
3. fMRI cartography + representational geometry on the same contrasts
4. probes/decoders for candidate information
5. sparse feature discovery where justified
6. attribution/circuit analysis on high-value cases
7. causal intervention to validate important claims
8. held-out predictive challenge

This is a default, not a rigid pipeline. High-information cheap tests may be repeated throughout the process.
