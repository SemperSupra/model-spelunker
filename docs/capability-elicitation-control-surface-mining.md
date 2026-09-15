# Capability Elicitation & Control-Surface Mining

## Mission

Discover and qualify model-specific and model-family-level control surfaces that unlock latent capability, improve reasoning reliability, or reduce required model scale; then package robust findings into agent-framework adapters and qualification checks.

The objective is deliberately broader than prompt engineering. We distinguish:

- **elicitation levers** — prompts, phrases, examples, control tokens, templates, context layout, tool schemas, role/policy framing, output constraints;
- **capability amplifiers** — framework-level mechanisms such as decomposition, external scratchpads, search, self-consistency, verifier loops, retrieval, tool-assisted checking, adaptive test-time compute, and structured execution;
- **model-control signals** — measurable internal or output-probability signatures that predict when a lever is helping or harming;
- **qualified recipes** — robust, evidence-backed combinations promoted into model adapters or agent qualification.

Do not assume a useful lever is a literal “magic phrase.” Some of the strongest gains may come from serialization fidelity, decomposition, verification, or tool use rather than natural-language incantations.

## Why this belongs in Model Spelunker

Model Spelunker is already intended to recover capabilities, limitations, protocol dependencies, representations, and mechanisms. Elicitation mining asks the complementary operational question:

> Given a model that appears weak under default interaction, what controllable changes expose capability that is already latent or make the model-framework composite use that capability more effectively?

This is especially valuable for smaller models because framework support can sometimes substitute for model-internal capacity or weak self-verification.

## Control-surface taxonomy

### C0 — Native serialization and control tokens

Recover and validate the exact chat template, BOS/EOS behavior, generation prompt, role tokens, tool-call serialization, document/retrieval serialization, and special control tokens.

Treat these as part of the model interface, not cosmetic formatting.

### C1 — Instruction and lexical elicitation

Search for semantically meaningful instruction variants, delimiters, task framing, examples, demonstrations, decomposition wording, answer-format constraints, and language choice.

Literal trigger phrases may exist, but must survive paraphrase and holdout testing before being treated as more than brittle prompt artifacts.

### C2 — Context construction

Vary ordering, chunking, salience, recency, retrieved evidence placement, demonstrations, negative examples, and context compression.

Measure capability gain separately from mere answer-style changes.

### C3 — Reasoning/scaffolding policy

Compare direct answer, decomposition, least-to-most style planning, external scratchpad, plan/execute separation, critique/revision, self-consistency, best-of-N, tree/beam search, and other test-time compute strategies.

### C4 — Verification and oracle support

Evaluate self-verification, independent verifier models, deterministic validators, code execution, calculators, retrieval, symbolic solvers, and domain-specific checkers.

Prefer external deterministic verification when the target weakness is memorization/calculation rather than inference.

### C5 — Tool affordance/interface design

Vary tool names, descriptions, schemas, argument structure, result serialization, tool ordering, error messages, retry policy, and whether tools are exposed simultaneously or progressively.

The model may possess the relevant capability but fail to express it under a mismatched tool protocol.

### C6 — Sampling and inference policy

Search temperature/top-p/top-k, candidate count, stopping, constrained decoding, speculative branches, verifier allocation, and compute-budget allocation.

Treat sampling policy as part of the model-framework composite, not the model alone.

### C7 — Retrieval and external memory

Measure when retrieval, episodic state, structured notes, or cached intermediate results improve reasoning versus distract or induce anchoring.

### C8 — Learned or activation-level steering (open models only)

Where access permits, test soft prompts, activation steering, representation patching, learned prefix/control vectors, or other interventions. These are higher-access-tier controls and require separate causal/robustness qualification.

## Search strategy

For each target capability:

1. establish a strict baseline;
2. enumerate candidate control surfaces from model metadata, native templates, documentation, prior art, and exploratory probes;
3. run cheap screening to eliminate low-value factors;
4. perform controlled factorial/fractional-factorial or adaptive search over promising factors;
5. inspect probability surfaces and internal signals where available;
6. use delta-debugging/minimization to reduce successful recipes to their smallest effective components;
7. challenge the recipe with paraphrases, domain transfer, reordered context, unseen tasks, and model/version changes;
8. compare direct-model and framework-mediated behavior;
9. measure gain, cost, variance, fragility, and failure modes;
10. promote only robust recipes into a versioned Model Elicitation Profile.

## Model Elicitation Profile

This is distinct from OAS `PolicyProfile`/persona.

- `PolicyProfile` describes **how an actor approaches work**.
- `ModelElicitationProfile` describes **how a specific model or model family should be interfaced with and scaffolded to expose its capabilities reliably**.

A minimal profile may contain:

```yaml
model_match:
  family: ...
  revision_range: ...

serialization:
  chat_template: native
  generation_prompt: ...

tool_protocol:
  schema_style: ...
  result_format: ...

reasoning_policy:
  default: direct
  escalate_when: ...
  strategies:
    - decomposition
    - self_consistency
    - tool_verified

sampling:
  temperature: ...
  candidate_count: ...

qualification:
  evidence_bundle: ...
  holdout_gain: ...
  known_failure_modes: ...
```

The profile is an optimization/compatibility artifact, never an authority artifact.

## “Cheat code” graduation criteria

A candidate lever should not be promoted because it creates a striking demo. Require evidence of:

1. **uplift** — meaningful improvement over native/default baseline;
2. **repeatability** — effect persists across repeated stochastic runs;
3. **holdout validity** — improvement survives unseen tasks/examples;
4. **semantic robustness** — not destroyed by harmless paraphrase unless the effect is explicitly protocol/token-specific;
5. **scope clarity** — domains/tasks where it helps and harms are known;
6. **cost effectiveness** — gain is worthwhile relative to tokens, latency, compute, and tools;
7. **framework portability or explicit specificity** — whether it transfers across wrappers/frameworks is measured;
8. **version sensitivity** — behavior across checkpoints/quantizations is recorded;
9. **failure-mode characterization** — false confidence, verbosity, tool misuse, degeneration, and other costs are measured;
10. **provenance** — exact model, tokenizer, prompt bytes/tokens, configuration, and framework version are preserved.

## Small-model-first program

Begin with small open models because they allow cheap high-rep experiments and deeper instrumentation.

For each selected family, build a capability surface across:

- direct baseline
- native-template baseline
- best discovered lexical/instruction elicitation
- best context construction
- decomposition/scaffold
- self-consistency/search
- verifier-assisted
- tool-assisted verification
- full qualified composite

Measure both absolute performance and **capability uplift per unit compute**.

Then repeat on successively larger checkpoints to determine whether a technique:

- is uniquely valuable for small models;
- remains beneficial at larger scale;
- becomes redundant as model capability increases;
- changes form with scale;
- transfers across families.

## Agent-framework integration

The agent framework should not hard-code one universal reasoning recipe.

Instead, allow a model adapter to expose a qualified `ModelElicitationProfile` and let the framework select among validated strategies under budget and task conditions.

Conceptually:

```text
work item
   ↓
agent policy
   ↓
model adapter
   ├─ native serialization
   ├─ model-specific tool protocol
   ├─ qualified elicitation profile
   └─ escalation policy
   ↓
reasoning model
```

The framework may escalate from cheap/direct execution to more expensive scaffolds only when confidence, task type, or validation signals justify it.

## Qualification interaction

Model Spelunker discovers candidate levers. Agent qualification determines whether they are operationally trustworthy.

A promoted technique should be tested at:

- Q0 reasoning model
- Q2 model × framework composite
- Q3 embodied agent where relevant

This prevents a model-level “cheat code” from being assumed beneficial after framework serialization, memory, retries, or tool mediation are introduced.

## Initial experiments

Use the existing protocol-sensitive tool-use experiment as seed evidence.

For each small-model target:

1. native vs generic serialization;
2. direct vs decomposed reasoning;
3. single-sample vs self-consistency/best-of-N;
4. self-verification vs deterministic/tool verification;
5. tool schema and result-format variants;
6. same conditions direct-to-model vs through the minimal agent framework;
7. fMRI/geometry/probability-surface observation of the conditions with the largest behavioral deltas.

The first objective is not to maximize benchmark score. It is to discover which control surfaces produce reproducible capability deltas and which internal/behavioral signals predict those deltas.
