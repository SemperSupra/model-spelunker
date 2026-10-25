# Prior-Art Sweep and Red/Blue Review

## Bottom line

Model Spelunker should not invent a new scientific method. Its value is the disciplined composition of mature primitives from multiple fields into an operational methodology for recovering the behavior, semantics, state, internal organization, limitations, and causal structure of an unknown model.

The architecture therefore adopts established terminology and mechanisms wherever possible, and reserves new terminology for genuinely new integration points.

## Established disciplines and primitives to adopt

### 1. Test, Evaluation, Verification, and Validation (TEVV)

Use TEVV as the outer assurance frame rather than inventing a generic confidence framework.

Adopt:
- explicit assessment objectives
- events/experiments separated from tools/instruments
- measurement concepts separated from measurement implementations
- documented test sets, metrics, tools, conditions, uncertainty, and limitations
- independent assessment where feasible

Relevant prior art:
- NIST AI 200-2 Initial Public Draft, TEVV-Athlon Framework (2026)
- NIST AI RMF measurement practices

### 2. Modeling-and-simulation credibility and validation hierarchy

Use the validation-hierarchy concept for progressive qualification of recovered model claims.

Adopt:
- quantities of interest / recovery targets
- hierarchical validation from component phenomena to integrated behavior
- verification versus validation distinction
- uncertainty characterization
- robustness assessment
- input/data pedigree
- use-history and process-rigor evidence
- gap analysis followed by sensitivity-based prioritization

Relevant prior art:
- NASA-STD-7009B
- NASA/JANNAF simulation credibility guidance

### 3. System identification

Treat black-box behavioral recovery as a system-identification problem where appropriate.

Adopt:
- input design as part of identification
- candidate model classes
- parameter/state estimation
- residual/model validation
- explicit distinction between identification fit and predictive validation
- sparse/parsimonious recovered models when possible

Related techniques such as SINDy are candidate adapters for dynamical/stateful behaviors, not mandatory foundations.

### 4. Optimal and sequential experimental design

Replace ad-hoc "interesting next probe" selection with explicit experiment-selection objectives.

Adopt:
- expected information gain
- model discrimination criteria
- uncertainty reduction
- sequential/adaptive experiment design
- cost-constrained design

Use competing hypotheses as first-class objects; select probes that maximally discriminate among them.

### 5. Active automata learning

For stateful behavior, directly adopt the established membership-query / equivalence-query / counterexample-refinement pattern.

Adopt:
- hypothesis automaton
- membership queries
- equivalence approximation
- counterexample analysis
- abstraction refinement
- caches and parallel query execution
- state/transition coverage strategies

LearnLib is mature prior art and should be evaluated for direct reuse or adapter integration rather than reimplementing its algorithms.

### 6. Conformance testing

After learning a behavioral/state model, challenge it using established FSM/LTS conformance-testing strategies rather than bespoke random probing alone.

Adopt/evaluate:
- W / Wp methods
- HSI / H methods
- state and transition covers
- ioco-style input/output conformance where applicable

### 7. Protocol reverse engineering

The analogy to unknown-model interaction is unusually strong: infer both a vocabulary and a grammar from traces and active experiments.

Adopt from Netzob-style practice:
- vocabulary/symbol inference
- grammar/state-machine inference
- passive + active inference
- inferred model -> simulation/generation -> fuzzing feedback loop
- explicit field/dependency/semantic inference

For Model Spelunker, "vocabulary" generalizes to input/output/control concepts and "grammar" to valid interaction/state behavior.

### 8. Metamorphic testing and the oracle problem

This is a core primitive for semantic and capability recovery when exact answers are unavailable.

Adopt:
- metamorphic relations as explicit artifacts
- input transformation plus expected output relation
- invariance and equivariance tests
- statistical/approximate relations for stochastic systems
- relation validation and provenance

Do not invent a new name for semantic-preserving transformations.

### 9. Differential / pseudo-oracle testing

Use independently implemented models, model versions, methods, and representations as pseudo-oracles while recording common-mode assumptions.

The result of differential testing is evidence of disagreement, not automatic identification of which system is correct.

### 10. Dynamic invariant detection / specification mining

Adopt the Daikon pattern of reporting **likely invariants** learned from traces rather than treating empirical regularities as proofs.

Adopt:
- candidate invariant families
- statistical filtering
- implication/redundancy suppression
- counterexample search
- test-suite adequacy feedback

This maps directly to Spelunker's need to recover stable behavioral/semantic rules from observations.

### 11. Delta debugging / witness minimization

Every surprising capability, failure, trigger, protocol dependency, or counterexample should be reduced when possible.

Adopt:
- minimal failure-inducing / behavior-inducing witness
- difference isolation between passing/failing or behavior-A/behavior-B cases

This should become an automatic follow-up TTP.

### 12. Fuzzing and coverage-guided exploration

Use state-aware and feedback-guided fuzzing patterns to explore unknown interaction spaces.

Adopt:
- mutation + generation
- corpus retention
- novelty/coverage feedback
- state-aware seed selection
- replayable witnesses

AFLNet/StateAFL demonstrate the practical value of coupling inferred state with exploration.

### 13. Global sensitivity analysis

Use mature screening methods before expensive interpretability sweeps.

Adopt:
- Morris-style low-cost screening
- Sobol/variance-based analysis when justified
- interaction/nonlinearity identification
- global rather than purely local perturbation analysis

This is particularly useful for identifying which prompt/protocol/control dimensions deserve deeper internal instrumentation.

### 14. Psychophysics, psychometrics, and computerized adaptive testing

Capability measurement should borrow the distinction between a latent trait and individual test items.

Adopt/evaluate:
- calibrated item banks
- item difficulty/discrimination
- adaptive item selection
- measurement uncertainty
- stopping when precision is sufficient

This can prevent "benchmark score = capability" thinking and improve query efficiency.

### 15. Representational similarity analysis (RSA)

For fMRI-style and internal comparisons, adopt RSA/RDM methodology rather than relying only on raw activation magnitude.

Adopt:
- condition-wise activity patterns
- representational dissimilarity matrices
- cross-layer / cross-model / cross-instrument comparisons
- bootstrap/randomization testing

RSA is explicitly designed to bridge behavior, computational models, and multivariate activity measurements.

### 16. Mechanistic interpretability evaluation

Use MIB-style known-ground-truth tasks and causal-variable/path recovery to evaluate internal inspection tools.

Adopt:
- model organisms / ground-truth tasks
- circuit localization scoring
- causal variable recovery
- concise/faithful recovery rather than visual plausibility

### 17. Causal abstraction and intervention

Use existing causal-abstraction terminology for claims about high-level computations realized by neural systems.

Adopt:
- explicit high-level causal model
- alignment hypothesis
- interchange interventions
- counterfactual behavioral agreement
- causal abstraction fidelity

### 18. Model extraction / functional cloning literature

Use this literature as a measurement reference, not as the mission framing.

Adopt:
- agreement/fidelity on a defined input domain
- query efficiency
- held-out functional agreement
- distinction between parameter recovery and functional recovery

All such testing is intended for models we are authorized to inspect.

## Cross-domain invariants worth making canonical

1. **The interface is part of the system under test.** Protocol/serialization/state must be characterized before attributing behavior solely to the model.
2. **Observation is not proof.** Trace-derived properties are "likely invariants" until challenged.
3. **Decodability is not causality.** A probe, RSA cluster, SAE feature, or activation contrast cannot by itself establish functional use.
4. **Hypotheses must face counterexamples.** Recovery proceeds by conjecture -> discriminating test -> counterexample -> refinement.
5. **No-oracle problems require relational evidence.** Prefer metamorphic relations, pseudo-oracles, and invariants when exact answers are unavailable.
6. **Minimize witnesses.** Reduce surprising behavior to the smallest reproducible condition set.
7. **Adaptive tests should maximize information, not novelty alone.** Use model discrimination / expected information gain under resource constraints.
8. **Screen cheaply before measuring expensively.** Global sensitivity / broad behavior tests precede large activation or circuit sweeps.
9. **Fit and validation are separate.** Never evaluate a recovered rule only on the observations used to infer it.
10. **State models require conformance challenge.** A learned automaton is a hypothesis, not the truth.
11. **Credibility is multi-dimensional.** Evidence quality, uncertainty, robustness, provenance, validation, and process rigor remain separate dimensions.
12. **Independent instruments can share failure modes.** Agreement is not independence; record common assumptions.
13. **Access constraints are epistemic constraints.** Claims must state what was observable/intervenable.
14. **Functional recovery is scoped.** High agreement over a defined domain is not identity of internal mechanism or global equivalence.
15. **Negative space is evidence.** Failed elicitation is not incapability until alternative protocols/probes and test adequacy have been considered.

## Red team: ways the current Model Spelunker design can fail

### R1. Tool-zoo failure
A large catalog of methods can create activity without increasing recovered knowledge.

Countermeasure: every method must demonstrate incremental value over simpler baselines through ablation.

### R2. Lowest-common-denominator schema
A universal ObservationBundle could flatten method-specific evidence and erase critical assumptions.

Countermeasure: common envelope + typed method-specific payloads; never force all methods into identical metrics.

### R3. Pseudo-independence
Multiple instruments may share the same stimuli, decoder, representation, model prior, or preprocessing and therefore make correlated errors.

Countermeasure: dependency graph for evidence; distinguish corroboration from independent replication.

### R4. Adaptive-probe overfitting
An autonomous experiment planner can repeatedly adapt to the same model and produce an impressive but non-generalizable characterization.

Countermeasure: frozen holdouts, blind challenge sets, precommitted evaluation slices, and separate discovery/validation budgets.

### R5. Ground-truth illusion
Real models rarely provide complete mechanism ground truth.

Countermeasure: distinguish C1 known-ground-truth model organisms, C2 blind planted-mechanism tests, and C3 ecological field characterization.

### R6. Intervention artifacts
Ablation/patching/steering can push representations off-distribution and create effects unrelated to normal computation.

Countermeasure: intervention-strength sweeps, distribution diagnostics, positive/negative controls, alternative intervention forms, and behavioral specificity tests.

### R7. fMRI metaphor overreach
The fMRI analogy may encourage spatial-localization thinking even when transformer representations are distributed, superposed, or dynamically routed.

Countermeasure: describe the method as activation cartography; pair it with geometry, distributed-feature, and causal methods.

### R8. Multiple-comparison archaeology
Large layer/token/feature sweeps can always find apparently meaningful patterns.

Countermeasure: correction, preregistered primary contrasts, permutation tests, replication, and held-out prediction.

### R9. Benchmark capture / Goodharting
Once a model or method is tuned to the calibration suite, measured recovery can stop reflecting real unknown-model performance.

Countermeasure: rotating hidden model organisms, adversarial evaluator-held cases, and out-of-family transfer tests.

### R10. Capability ontology lock-in
Starting with a fixed benchmark ontology can make the system discover only capabilities we already named.

Countermeasure: combine structured capability tests with open-ended anomaly/novelty search and unsupervised clustering.

### R11. Conflating absence of evidence with evidence of absence
A failed probe may reflect poor elicitation, wrong protocol, insufficient context, stochasticity, or an inaccessible capability.

Countermeasure: incapability claims require failed alternative elicitation strategies and explicit test-adequacy evidence.

### R12. Cost explosion
Running every instrument on every probe is computationally unsustainable.

Countermeasure: progressive funnel, sensitivity screening, adaptive experiment design, and explicit value-of-information/cost metrics.

## Blue team: strengthened architecture

### B1. Use TEVV as the outer shell
Define assessment objectives and quantities of interest first. Then select events/probes and tools/instruments. Preserve evidence and uncertainty separately from conclusions.

### B2. Use an identification loop, not a fixed pipeline

OBSERVE -> HYPOTHESIZE -> SELECT DISCRIMINATING EXPERIMENT -> EXECUTE -> SEARCH COUNTEREXAMPLE -> REFINE -> VALIDATE ON HOLDOUT

The loop should support multiple hypothesis formalisms: invariants, semantic relations, automata, causal models, capability frontiers, and predictive surrogates.

### B3. Progressive inspection funnel

Stage 0: interface/protocol characterization
Stage 1: cheap behavioral + metamorphic + differential reconnaissance
Stage 2: sensitivity screening and state discovery
Stage 3: targeted activation/RSA/probes
Stage 4: sparse-feature/attribution/circuit hypotheses
Stage 5: controlled interventions
Stage 6: blind held-out qualification

Expensive methods are pulled by uncertainty and expected information value rather than run indiscriminately.

### B4. Evidence dependency graph
Each claim records supporting observations, methods, shared assumptions, contradicting evidence, provenance, uncertainty, scope, and next falsification test.

### B5. Qualification through blind model organisms
The evaluator plants known behaviors, latent variables, redundant paths, rare triggers, misleading correlations, and protocol dependencies. The inspection system is scored before unblinding.

### B6. Method promotion by measured incremental value
A TTP becomes standard only when it improves at least one of:
- held-out predictive fidelity
- known-ground-truth recovery
- causal fidelity
- boundary resolution
- query/compute efficiency
- unique discovery of important behavior

## Adopt / adapt / build decisions

### Adopt directly or wrap
- TEVV terminology and assessment separation
- NASA-style credibility factors and validation hierarchy
- LearnLib-style active automata learning and equivalence/conformance machinery
- metamorphic testing terminology and relation structure
- Daikon-style likely-invariant semantics
- delta debugging witness minimization
- RSA/RDM methodology
- established global sensitivity methods
- established optimal experimental-design criteria

### Adapt to neural/model inspection
- protocol reverse engineering's vocabulary + grammar decomposition
- psychometric adaptive testing for capability frontiers
- state-aware fuzzing for interaction exploration
- system-identification residual validation
- causal abstraction and mechanistic benchmark methodology

### Build only where integration is genuinely missing
- common model-access adapter tiers A0-A4
- shared probe/evidence ledger spanning black-box through internal intervention methods
- evidence dependency graph across heterogeneous instruments
- autonomous method-selection policy using expected information gain, cost, and access tier
- holistic recovered-model package joining capability, semantic, protocol/state, failure, internal, and causal views
- comparative instrument-value benchmark focused on *incremental recovery of unknown models*

## Multilingual/global sweep note

Searches were deliberately repeated using English and non-English terminology (including German, Chinese, Japanese, French, and Spanish variants) to detect terminology drift and independent traditions. The strongest cross-language convergence was around the same established concepts: black-box/system identification, active automata/model learning, conformance testing, metamorphic testing/the oracle problem, and protocol inference. No separate non-English methodological tradition discovered in this pass displaced the mature primitives above. This is evidence from a broad sweep, not proof of exhaustive global coverage; the sweep should remain a repeatable research task.
