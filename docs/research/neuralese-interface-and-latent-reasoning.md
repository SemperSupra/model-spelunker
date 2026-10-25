# Neuralese Interface Discovery & Latent Reasoning

## Scope correction

The primary research target is not merely multilingual behavioral differences and not merely whether a concept is linearly decodable.

The stronger target is to determine whether a model contains an **internally useful latent representation system that can be discovered from the outside and then addressed deliberately**.

Operationally:

`external representation -> internal latent representation -> downstream use`

If this mapping can be discovered, validated causally, and reused, it becomes an addressable latent interface. "Neuralese" is a useful working name, but we should not assume language-like grammar or universality until evidence supports those claims.

A second, related target is **latent reasoning trajectory Neuralese**: whether multi-step computation proceeds through a sequence of internal states that can be observed, mapped, intervened on, and perhaps used directly without serializing every step into natural-language chain of thought.

These are connected but distinct experimental objects.

## Working taxonomy

### N0 — surface-language control

Natural-language prompts, explicit chain of thought, ordinary token generation, and conventional prompt optimization. This is the baseline, not Neuralese.

### N1 — representational Neuralese

Stable latent representations of concepts, relations, functions, goals, or task state that can be induced through different external forms.

Evidence questions:

- Do paraphrases and multiple languages converge on a shared internal state?
- Is the representation invariant to irrelevant surface form?
- Can it be decoded on held-out contexts?
- Does the representation survive changes in output language and task framing?

### N2 — workspace / addressable Neuralese

A privileged internal representation that can be both read and written and is reused by multiple downstream computations.

A strong example of the kind of evidence we seek is Anthropic's 2026 J-space work: internal concept patterns were readable, causally swappable, reusable by multiple downstream tasks, and involved in silent multi-step reasoning. We should reproduce analogous properties on open-weight models rather than treating any one implementation as universal.

Required properties for an addressable latent interface:

1. **Readability** — infer the represented concept/state from activations above appropriate controls.
2. **Writeability** — injecting/replacing the representation changes behavior as predicted.
3. **Context invariance** — the same representation remains usable across unrelated surface contexts.
4. **Task reuse** — one write can drive multiple distinct downstream computations.
5. **Cross-lingual transfer** — representations discovered through one language can affect reasoning entered through another language.
6. **Compositionality** — representations or operators can be combined predictably.
7. **Efficiency** — a compact external input can reliably reach the target state without requiring a long natural-language paraphrase.

Only after these properties begin to hold should we describe a discovered representation system as a practical Neuralese interface.

### N3 — trajectory / reasoning Neuralese

A sequence of latent states performs multi-step computation. This is distinct from a static concept representation.

Questions include:

- Does the model traverse reproducible latent states while solving structurally similar problems?
- Does explicit chain of thought expose those states, induce them, distort them, or merely correlate with them?
- Can intermediate latent states be causally swapped between problem instances?
- Can a latent state encode several candidate next steps without choosing a surface token yet?
- Are there reusable latent operators such as compare, bind, negate, carry, backtrack, retrieve, or verify?
- Do transition rules between states show anything grammar-like or program-like?

Coconut / Chain of Continuous Thought is an engineered example of this class: a final hidden state is fed back as the next input embedding rather than decoded into a token. Selective latent-reasoning methods such as SeLaR explore hybrids of continuous and discrete reasoning. These methods are experimental probes of trajectory Neuralese, not proof that ordinary models naturally use the same mechanism.

### Adjacent: inter-agent Neuralese

The older use of "Neuralese" for learned continuous messages between agents is adjacent and potentially useful as a comparison condition. It should not be conflated with either a model's internal concept space or its latent reasoning trajectory.

## Central hypotheses

### H-R1 — external-to-latent convergence

An equivalence class of external representations of the same concept maps to a lower-dimensional internal region or family of related regions more tightly than unrelated concepts do.

### H-R2 — causal addressability

The discovered representation is not just decodable. Writing or replacing it changes downstream model behavior in the direction predicted by the mapped concept.

### H-R3 — reusable latent state

A representation extracted in one task can be used by different downstream computations without retraining the representation for each task.

### H-R4 — cross-lingual latent transfer

A representation extracted through language A can causally influence computation expressed through language B, after controlling for tokenizer and fluency effects.

### H-R5 — external code discovery

It is possible to search external input space for short, robust inputs that reach a desired internal state more directly or efficiently than ordinary natural-language prompting.

This is the eventual "Neuralese prompt" objective. It is downstream of representation discovery and causal validation, not a first-stage prompt-engineering exercise.

### H-T1 — latent trajectory structure

Reasoning performance depends on structured trajectories through latent state space rather than only on the emitted chain-of-thought tokens.

### H-T2 — trajectory transfer

Intermediate states or operators can be transferred between problems and preserve some functional meaning.

### H-T3 — latent computation can outperform surface serialization

For some tasks, continuous or partially continuous latent reasoning can preserve or improve accuracy with fewer serialized reasoning tokens, while surviving adversarial and out-of-distribution tests.

## External-to-internal discovery loop

For each concept or function:

1. Generate a multilingual/multiform external equivalence class.
2. Capture layerwise hidden states at several defensible readout positions.
3. Measure within-concept convergence versus between-concept controls.
4. Fit the simplest representation hypothesis that survives held-out data: direction, subspace, polytope, prototype family, or nonlinear manifold.
5. Test **read** on unseen paraphrases/languages/contexts.
6. Test **write** through activation injection, replacement, patching, or erasure.
7. Test **transfer** across language and task.
8. Test **reuse** across multiple downstream questions requiring the same internal concept.
9. Test **composition** of two or more discovered representations/operators.
10. Only then search for minimal external inputs that reliably target the representation.

The desired endpoint is not merely a dictionary from words to vectors. It is a measured map:

`external code E -> latent state Z -> causal capability F`

with uncertainty, scope, layer/token location, model revision, and provenance attached.

## Latent reasoning / chain-of-thought loop

Use compute-matched conditions wherever possible:

1. direct answer / no explicit CoT
2. explicit textual CoT
3. hidden-state trajectory observation during ordinary generation
4. answer-only prompting with latent-state instrumentation
5. continuous hidden-state recurrence (Coconut-style) when a suitable model/checkpoint is available
6. soft-embedding or selectively latent reasoning methods

For each condition record:

- answer quality
- serialized token budget
- forward-pass / compute budget
- hidden-state trajectory
- intermediate concept readouts
- intervention sensitivity
- OOD/adversarial performance
- shortcut sensitivity

Do not equate higher benchmark accuracy with faithful reasoning. Recent adversarial analysis of continuous-thought systems argues that apparent latent reasoning can exploit shortcuts, so causal intervention and OOD controls are mandatory.

## Relationship to Experiment 0001

Experiment 0001 remains useful as a cheap calibration/falsification stage for probe construction, language matching, tokenization, and measurement artifacts.

It is **not** the primary Neuralese experiment.

Its job is to produce clean external equivalence classes and controls. Those become inputs to representation-interface discovery. A behavioral effect is not required for promotion if a probe family is semantically high-quality and useful for testing latent convergence; conversely, a behavioral anomaly alone is insufficient evidence of Neuralese.

## Adopt-before-build primitives

Prefer established techniques as independent observers and interventions:

- linear / causal representation hypotheses
- counterfactual concept vectors
- representation engineering / activation steering
- function vectors
- CCA / Procrustes / representational similarity for alignment
- activation patching / causal tracing
- concept erasure
- distributed alignment / causal abstraction
- sparse feature dictionaries only as one observer, not the ontology
- Jacobian-based lenses / J-space-style methods where reproducible on open models
- continuous-thought / soft-thought latent reasoning methods for trajectory experiments

The research contribution should come from combining these primitives into a falsifiable external-to-latent discovery loop, not from inventing a bespoke interpretability stack.

## Evidence ladder for Neuralese claims

- **N-E0:** external behavioral regularity only.
- **N-E1:** latent state is reliably decodable across held-out surface forms.
- **N-E2:** representation is invariant across meaningful changes in language/context.
- **N-E3:** causal write/erase/replace changes downstream behavior predictably.
- **N-E4:** representation transfers across tasks/languages and is reused by multiple computations.
- **N-E5:** multiple discovered representations/operators compose predictably.
- **N-E6:** compact external codes can deliberately and robustly address the latent interface.

For trajectory Neuralese add:

- **T-E1:** reproducible latent trajectory structure.
- **T-E2:** intermediate-state intervention changes later reasoning as predicted.
- **T-E3:** states/operators transfer between problem instances.
- **T-E4:** latent reasoning survives compute-matched, adversarial, and OOD controls.

## Immediate implementation consequence

The next Model Spelunker work should add two distinct experiments:

- **Experiment 0002 — External-to-Latent Interface Discovery**
- **Experiment 0003 — Latent Reasoning Trajectories / Neuralese CoT**

Experiment 0001 continues as the probe-quality and confound-control feeder for both.