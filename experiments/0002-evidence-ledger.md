# Experiment 0002 — Executed Evidence Ledger

This file preserves compact, decision-relevant evidence after ephemeral CI artifacts expire. It is not a second experiment specification. Detailed machine records remain in the referenced workflow artifacts while retained.

## Evidence rules

- Record executed method separately from planned method.
- Preserve nulls, exclusions, compatibility fixes, and failed hypotheses.
- Pin model, lens, upstream method/data, and workflow run identifiers.
- Do not promote behavioral or observer-only effects into causal Neuralese claims.
- Add only evidence that changes confidence or the next experiment decision.

## E0002-R1 — one-direction reciprocity read/write smoke

**Models:** Pythia-70m and Qwen3-0.6B-Base.

**Executed:** derive one P-vs-N reciprocity direction from six training probes, choose layer on training data, evaluate 12 held-out probes, then inject the direction into held-out negative cases against a norm-matched random direction.

**Result:** both models fit the six training probes but fell to 50% held-out readout. Intervention effects were inconsistent across language/dose and did not support a reusable one-vector representation.

**Decision:** reject `concept = one mean-difference vector` as the working ontology for reciprocity. Keep the intervention apparatus; move toward J-space/subspace/workspace observers.

## E0002-R2 — pinned Jacobian-lens observer calibration

**Model:** `EleutherAI/pythia-70m-deduped@e93a9faa9c77e5d09219f6c868bfc7a1bd65593c`

**J-lens upstream:** `anthropics/jacobian-lens@581d398613e5602a5af361e1c34d3a92ea82ba8e`

**Pre-fitted lens:**

- repo: `neuronpedia/jacobian-lens`
- revision: `91271eb5b15a43eebed7bb447618738754f1379a`
- file: `pythia-70m-deduped/jlens/Salesforce-wikitext/pythia-70m-deduped_jacobian_lens.pt`
- fitting prompts recorded by lens: 1000

**Executed deviation/compatibility fixes:**

1. pinned upstream expected the historical GPT-NeoX unembedding name `embed_out`; current Transformers exposes `lm_head`. Used an explicit `jlens.Layout` without patching upstream;
2. upstream `snapshot_download()` hit an unauthenticated Hugging Face 429 while listing the lens repository. Switched to direct `hf_hub_download()` of the single pinned lens file.

**Result:** on four hand-authored hidden-intermediate calibration cases, J-lens best rank beat vanilla logit lens in 4/4 cases; median best target rank was 5 under J-lens vs 23 under vanilla. One case remained poor under both observers.

**Decision:** observer is operational and earns use as an independent microscope. This is observer calibration only, not causal Neuralese evidence.

## E0002-R3 — released probe-swap strict causal attempt

**Workflow run:** `35055541841`

**Model/lens:** same pinned Pythia/J-lens pair as E0002-R2.

**Dataset:** Anthropic released `data/experiments/probe-swap.json` at upstream commit `581d398613e5602a5af361e1c34d3a92ea82ba8e`.

**Dataset SHA-256:** `a0edd27ca23f7b4d0fbe90448c2ddcc7457a3d812121bf024ed12a032ff86796`

**Executed:** paper-faithful two-coordinate J-space swap with direct-answer and norm-matched-random controls; only clean-top-1-correct, single-token cases were eligible for intervention.

**Result:** 0/90 cases were eligible because Pythia-70m produced zero clean top-1 published answers. The run therefore measured no bridge interventions.

**Decision:** this is a model/task capability failure, not evidence against the swap primitive or latent-interface hypothesis. The strict eligibility gate hid weaker but potentially diagnostic causal effects, so a second calibration retained the strong criterion while adding pairwise preference evidence.

## E0002-R4 — released probe-swap preference/dose/layer calibration

**Workflow run:** `35056635786`

**Artifact ID:** `10431165825`

**Model/lens/data:** identical pinned Pythia/J-lens/data provenance to E0002-R3.

**Executed:** exact released two-coordinate pseudoinverse swap. Scored all cases for which intermediate, replacement, answer, and counterfactual answer had usable single-token forms. Added only:

- strengths 0.5, 1.0, 2.0 on all fitted layers;
- early-half vs late-half fitted-layer ablation at strength 1.0;
- strong clean-top-1 -> counterfactual-top-1 criterion;
- weaker clean answer-vs-counterfactual preference -> reversed preference criterion.

**Scored:** 74/90 cases; 16 skipped for single-token eligibility.

**Baseline:**

- clean top-1 published answer: 0/74;
- clean pairwise preference for published answer over counterfactual: 39/74.

**Preference flips among the 39 eligible pairwise-baseline cases:**

| Condition | Flips | Rate |
| --- | ---: | ---: |
| all fitted, 0.5x | 4/39 | 10.3% |
| all fitted, 1.0x | 10/39 | 25.6% |
| all fitted, 2.0x | 21/39 | 53.8% |
| early fitted half, 1.0x | 2/39 | 5.1% |
| late fitted half, 1.0x | 9/39 | 23.1% |

Mean answer-minus-counterfactual margin change became increasingly negative with intervention strength; at 1.0x the late-half effect was materially larger than the early-half effect.

**Interpretation:** dose- and layer-structured causal influence exists at the pairwise-preference level. Because Pythia never satisfied the clean top-1 baseline, this cannot establish the released strong causal-swap result.

**Decision:** retire Pythia-70m as the primary causal target. Do not spend additional reps tuning it. Promote the same primitive to a behavior-capable model/lens pair.

## E0002-R5 — Qwen3.5 multilingual bridge observer calibration

**Workflow run:** `35056201459`

**Artifact ID:** `10430484107`

**Model:** `Qwen/Qwen3.5-0.8B@2fc06364715b967f1860aea9cf38778875588b17`

**Pre-fitted lens:**

- repo: `neuronpedia/jacobian-lens`
- revision: `4f30bb8c97e696115d4a2ef359923b5005fc860c`
- file: `qwen3.5-0.8b/jlens/Salesforce-wikitext/Qwen3.5-0.8B_jacobian_lens.pt`
- source layers: 0–22
- fitting prompts recorded by lens: 233

**Executed:** 12 indirect hidden-bridge prompts: four concepts × English/German/Thai. The prompt omitted the hidden country bridge; J-lens and vanilla logit-lens ranks were compared over late prompt positions. A short free-generation continuation was also used as the first behavioral check.

**Result:** J-lens best hidden-bridge rank beat vanilla in 12/12 cases. Median best ranks were:

- English: J-lens 22 vs vanilla 373.5;
- German: J-lens 77.5 vs vanilla 605.5;
- Thai: J-lens 4389.5 vs vanilla 41344.5.

The free-generation behavior check was 0/12, but continuations frequently emitted model thinking/chat scaffolding or repeated prompt text, making that behavioral metric confounded rather than a clean knowledge test.

**Decision:** Qwen3.5-0.8B + published J-lens earns the next behavior-valid calibration. Do not interpret the 0/12 free-generation result as absence of bridge knowledge. A forced-choice continuation-likelihood cloze rep is the current gate before causal multilingual patching.

## Current promotion gate

1. Complete behavior-valid Qwen3.5 multilingual bridge cloze calibration.
2. If Qwen demonstrates usable surface competence, run a small causal probe-swap rep on the same already-qualified model/lens pair.
3. Require strong top-1 causal swaps where baseline correctness permits; retain pairwise preference flips only as secondary evidence.
4. If causal swapping works, build the first English/German/Thai cross-language patch using the same hidden bridge identities.
5. Only after cross-language causal transfer succeeds, promote a candidate toward `addressable Neuralese`; downstream reuse remains required.
