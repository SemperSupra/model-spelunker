# Experiment 0001 — Behavioral Multilingual Concept Geometry

## Goal

Find reproducible concept/language effects cheaply enough to run on public CPU-only CI before investing in internal instrumentation.

## Null hypothesis

After controlling for prompt form, translation fidelity, tokenization, and output language, multilingual formulations of the same concept do not produce materially different behavioral outcomes beyond normal sampling variation.

## Alternative hypotheses

- H1: some concepts are accessed more reliably through particular languages or culturally native formulations.
- H2: mixed-language or semantic-decomposition probes improve performance over direct single-language prompts.
- H3: boundary and discovery probes reveal systematic concept-neighborhood asymmetries that are stable across paraphrases.
- H4: effects are model-specific rather than universal.

## Initial concept set

Use concepts with known lexical/cultural structure rather than politically or clinically sensitive concepts for the first infrastructure reps. Seed candidates:

- obligation / duty / responsibility
- permission / authority
- respect / deference
- shame / embarrassment
- hospitality
- reciprocity
- privacy
- fairness
- trust
- belonging

The final seed set should include concepts where languages partition meaning differently, plus several deliberately boring controls such as concrete physical categories.

## Languages

Start with a small typologically diverse set that the generation/validation pipeline can support well. Suggested first wave:

- English
- German
- Thai
- Japanese
- Mandarin Chinese
- Spanish

Do not expand language count until matched-probe quality is measurable.

## Probe construction

For each concept-language pair create:

- 4 P probes
- 4 N probes
- 4 B probes
- 4 D probes

For every underlying semantic item, generate at least two independently phrased variants.

Keep a language-neutral semantic record separate from the surface realization so the same concept item can be rendered in multiple languages without losing identity.

## Tasks

Use small tasks with machine-checkable or structured outputs wherever possible:

1. concept membership classification
2. nearest-concept selection
3. contrastive preference
4. boundary judgment
5. short structured explanation scored against reference features
6. cross-language consistency test

Free-form generation is retained as evidence but should not be the only scoring surface.

## Controls

- randomized option order
- randomized prompt-template order
- matched output language
- English-only paraphrase control
- literal-translation versus native-formulation control
- token-count covariate
- character-count covariate
- tokenizer fragmentation statistics
- nonsense-label control
- concrete-category control
- held-out probe set

## Execution plan

Run in shards sized to fit the available public CI runner. A shard is bound to one model revision and contains multiple concept/language probes so model load/setup cost is amortized.

Each shard writes only compact structured results and compressed raw outputs as ephemeral CI artifacts. Model binaries are acquired through the Model Foundry provenance path and are not committed to git history.

Recommended batching key:

`model_revision x tokenizer_revision x prompt_template_version`

Within a runner, execute as many concept/language cases as the memory and time envelope allows before teardown.

## Required run metadata

- exact model/revision
- tokenizer/revision
- artifact digest
- prompt template version
- semantic probe ID
- surface realization ID
- language
- P/N/B/D class
- seed / deterministic generation settings
- input token count
- tokenizer fragmentation metrics
- wall time
- raw result reference
- machine score

## Analysis

Primary comparisons:

- language effect within the same semantic probe
- formulation effect within the same language
- P/N/B/D sensitivity
- model x language interaction
- model x concept interaction
- tokenization-adjusted effect
- paraphrase stability

Do not rank languages globally. Report concept/model-local effects with uncertainty.

## Promotion gate

A signal is eligible for Model Spelunker internal instrumentation only if it:

1. repeats across independent paraphrases;
2. survives held-out probes;
3. is not explained by length/token fragmentation alone;
4. has a stable direction across at least two task forms;
5. remains visible under deterministic or low-temperature evaluation;
6. is large enough to justify the next-stage compute.

## Falsification outcomes

This experiment is useful even if no multilingual advantage is found. Valuable negative outcomes include:

- all apparent gains collapse after tokenization control;
- culturally adapted prompts add no signal beyond paraphrase diversity;
- effects fail held-out probes;
- mixed-language inputs consistently hurt performance;
- effects are entirely model-specific and unstable.

These results constrain later neuralese claims and prevent expensive mechanistic work on artifacts.

## Next stage

For promoted concept/model pairs, capture layerwise hidden states and compare language-conditioned trajectories using multiple observers. No SAE requirement is imposed at promotion time.
