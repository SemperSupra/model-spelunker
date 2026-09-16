# model-spelunker

Public-safe research artifacts for independently checking public claims about model behavior and, where justified, model internals.

## Repository role

This repository owns public study declarations, public-safe experiment code, reproduction/replication protocols, and intentionally public evidence. It does **not** own portfolio research priorities, private hypotheses, private concept maps, hidden benchmark portfolios, private failure corpora, or promotion/acceptance authority.

Execution is intentionally separated from study semantics:

- `SemperSupra/model-spelunker` — public study/protocol/code authority for intentionally public research;
- `SemperSupra/agent-dispatch` — existing generic public execution/materialization plane, including sealed public execution;
- `SemperSupra/model-artifact-foundry` — immutable model/benchmark identity and provenance where registered;
- private research repositories — private selection, synthesis, novel hypotheses, value-bearing evaluator knowledge, and acceptance decisions.

Do not add a second scheduler or generic public compute hub here merely because a study needs compute.

## Minimum experiment evidence contract

Keep the hot path small. Reuse artifacts the study already needs rather than adding a separate experiment-management system:

- the study declaration is the planned methodology;
- the pre-dispatch capsule manifest seals the exact plan and method bytes;
- execution emits a receipt for the actual plan/method bytes plus the result bytes;
- the result records the actual environment, resolved artifacts/inputs, execution outcome, and scientific outcome;
- `tools/check_plan_execution.py` compares the sealed plan with the executed receipt and reports only material deviations.

Exploration is not blocked by extra ceremony. Promotion of a run as durable evidence requires enough of this chain to identify what was planned, what actually executed, and the resulting evidence. Add fields or mechanisms only when they improve rerunnability, interpretation, falsification, provenance, or evidence preservation.

## Evidence vocabulary

Top-level evidence classes are intentionally orthogonal to variation dimensions.

Evidence classes:

- `computational_reproduction`
- `independent_reimplementation`
- `direct_replication`
- `conceptual_replication`
- `robustness_sensitivity`
- `generalization_transport`
- `mechanism_test`
- `benchmark_audit`
- `meta_synthesis`

Variation dimensions such as model family, checkpoint, dataset, language, geography, time, harness, precision, preprocessing, evaluator, and adversarial perturbation are recorded separately rather than encoded into proliferating study-type names.

Execution and scientific dispositions are independent. A well-executed study that does not support a claim is still a successful execution and useful evidence.

## First specimen

`studies/siglip2-model-card-zsic-001/` is a bounded computational reproduction of the public SigLIP2 model-card zero-shot image-classification usage example. It is explicitly **not** represented as a reproduction of the SigLIP2 paper benchmark tables.

The specimen:

1. binds the model to the Model Artifact Foundry approved identity and per-file SHA-256 values;
2. reacquires the exact upstream revision and verifies each declared file before inference;
3. records the exact acquired stimulus-byte hash;
4. hashes the realized `pixel_values` tensor actually presented to the model;
5. records selected bounded vision-layer activation summaries without claiming those summaries explain the model;
6. records separate execution and scientific dispositions;
7. can be packed as a bounded capsule for the existing Agent Dispatch sealed public-execution contract.

Build the capsule locally or in an authorized coordinator environment:

```bash
python3 tools/build_sealed_capsule.py studies/siglip2-model-card-zsic-001 --out .capsule
```

After execution and trusted result pickup, compare the sealed pre-execution manifest with the executed result bundle:

```bash
python3 tools/check_plan_execution.py .capsule/capsule-manifest.json <result-dir>
```

The generated capsule is execution material, not durable research authority. The public Agent Dispatch worker should execute it; substantive result interpretation belongs to the study's owning research authority.
