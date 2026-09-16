# Experiment 0003 — Latent Reasoning Trajectories / Neuralese CoT

## Goal

Study whether multi-step reasoning is better characterized as a trajectory through latent model states than as the natural-language chain of thought itself, and test whether those latent states can be read, causally manipulated, transferred, and eventually used directly.

This experiment is related to Experiment 0002 but studies a different object:

- Experiment 0002: **what latent representation is present?**
- Experiment 0003: **how does latent state evolve while computation proceeds?**

## Competing hypotheses

### H1 — latent-trajectory mediation

Reasoning depends on structured internal state transitions. Explicit CoT is one way to induce or expose portions of the trajectory, but is not the primary computational object.

### H2 — surface-CoT mediation

The serialized natural-language reasoning steps themselves carry most of the task-relevant state; hidden trajectories do not add much beyond what is represented in the emitted tokens.

### H0 — generic serial compute

Performance gains attributed to either CoT or latent reasoning are primarily explained by additional sequential compute rather than a privileged representation or trajectory.

Experiments must explicitly distinguish these hypotheses.

## Method families

### Passive trajectory observation

Instrument ordinary open-weight models while they solve matched problems under:

- direct answer
- explicit chain of thought
- answer-only with additional compute where available
- paraphrased/multilingual instructions

Capture layerwise states across generation. This requires no latent-reasoning training and is the cheapest starting point.

### Hidden-state intervention

Identify candidate intermediate states such as entities, subgoals, intermediate numeric values, relation states, or verification states and:

- patch them between examples
- replace one candidate state with another
- erase candidate states
- shift them using representation directions from Experiment 0002

Measure whether later reasoning follows the intervention.

### Continuous hidden-state recurrence

Coconut-style systems replace some serialized reasoning tokens with continuous hidden states that are fed back as subsequent input embeddings. Use the official/reference implementation where practical rather than creating a bespoke mechanism.

### Soft / selective latent reasoning

Methods such as soft-token reasoning and SeLaR use mixtures of token embeddings or activate latent reasoning selectively at uncertain steps. Treat these as additional conditions once the passive/intervention harness is sound.

## Initial tasks

Start with tasks where intermediate computational state is well-defined and machine-checkable:

1. short arithmetic with intermediate values
2. entity bridge questions (A -> B -> answer)
3. graph reachability / shortest simple path
4. symbolic relation composition
5. small planning problems with a required backtrack

Avoid free-form commonsense tasks for the first causal reps because intermediate-state ground truth is weak.

## Compute-matched conditions

For each task create comparable conditions:

- **C0 direct:** minimal answer generation
- **C1 text-CoT:** explicit natural-language reasoning
- **C2 serial-control:** extra serial compute without informative CoT where feasible
- **C3 latent-observed:** same model/output condition with hidden trajectory instrumentation
- **C4 continuous:** Coconut-style latent recurrence when available
- **C5 hybrid:** selective soft/latent reasoning when available

Record both token budget and forward-pass/compute budget. Never claim latent reasoning superiority from token count alone.

## Trajectory representation

For each generated step / latent step retain compact state descriptors across layers:

- residual-stream hidden state
- candidate concept/workspace readouts from Experiment 0002
- optional attention/MLP derived summaries
- output distribution entropy
- emitted token when applicable

Avoid committing full activation tensors to git.

## Analysis questions

### 1. Reproducible state sequence

Do structurally similar problems traverse analogous latent states despite different wording, values, or languages?

### 2. CoT correspondence

For explicit CoT, determine whether textual reasoning steps align temporally and causally with hidden-state changes. A surface explanation may be correlated, lagging, leading, or unrelated.

### 3. Silent intermediate states

Look for necessary intermediate concepts/values that appear internally even when never emitted.

### 4. Causal trajectory edits

If an intermediate state is replaced with a counterfactual one, does subsequent computation continue consistently from the injected state?

Example pattern:

`spider -> 8`

replace latent `spider` with `ant`

predicted continuation:

`ant -> 6`

The important evidence is that downstream computation consumes the changed internal state rather than merely changing one output token.

### 5. Transferable latent operators

Test whether a state transition corresponding to an operation can transfer across instances:

- add
- compare
- negate
- retrieve
- bind relation
- verify
- branch
- backtrack

Do not assume these are vectors; test directions, subspaces, and learned low-rank operators as competing hypotheses.

### 6. Composition / grammar-like structure

Only after transferable operators are found, test whether ordered compositions predict later states. Evidence for a "Neuralese grammar" requires reusable transition structure; recurring clusters alone are insufficient.

## Multilingual link

Use semantically matched multilingual versions of the same reasoning problem to ask:

- does language affect only early encoding and late decoding?
- do middle reasoning trajectories converge?
- do intermediate states transfer across languages?
- can a latent state extracted from an English run patch a Thai/German run?
- does the model choose different latent routes for culturally or lexically different formulations?

This connects trajectory Neuralese directly to the multilingual concept-sweep infrastructure.

## Continuous-thought falsification controls

Recent work challenging continuous-CoT systems argues that latent tokens can hide shortcut use rather than faithful reasoning. Therefore every continuous/hybrid condition must include:

- adversarial counterexamples
- dataset-artifact perturbations
- out-of-distribution structure
- counterfactual intermediate-state edits
- matched serial-compute controls
- test-time steering/ablation sensitivity

A latent system that scores well but fails causal intermediate-state tests does not earn a reasoning claim.

## Metrics

Prefer primitive measurements over a bespoke composite score:

- answer accuracy
- OOD accuracy
- adversarial accuracy
- emitted reasoning tokens
- forward passes / latent steps
- trajectory alignment across matched problems
- intermediate-state readout accuracy
- intervention success rate
- downstream consistency after state swap
- cross-language patch-transfer rate
- operator transfer rate
- state/transition stability across paraphrases

## Evidence ladder

- **T-E0:** behavioral gain only.
- **T-E1:** reproducible latent trajectory associated with task structure.
- **T-E2:** intermediate latent states contain expected hidden variables on held-out problems.
- **T-E3:** causal state intervention redirects later reasoning predictably.
- **T-E4:** state or operator transfers across problem instances or languages.
- **T-E5:** multiple operators compose predictably.
- **T-E6:** a latent/continuous reasoning system uses those validated states/operators robustly under compute-matched OOD/adversarial tests.

## First implementation slice

Do not start by training Coconut from scratch.

1. Build a hidden-state trajectory capture harness on a small open model.
2. Use two-step arithmetic/entity-bridge tasks with known intermediate states.
3. Compare direct answer versus explicit CoT.
4. Test whether the known intermediate state is linearly/nonlinearly readable before it is emitted.
5. Patch a counterfactual intermediate state and measure whether the downstream answer follows it.
6. Repeat the patch cross-lingually.
7. Only after this works, introduce an existing continuous-thought implementation/checkpoint or train the smallest feasible controlled model.

This gives the research program a causal baseline before continuous-CoT complexity is added.