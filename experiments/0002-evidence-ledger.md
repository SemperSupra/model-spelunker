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

**Decision:** Qwen3.5-0.8B + published J-lens earns the next behavior-valid calibration. Do not interpret the 0/12 free-generation result as absence of bridge knowledge.

## E0002-R6 — Qwen3.5 behavior-valid multilingual bridge cloze

**Workflow run:** `35056626692`

**Artifact ID:** `10430563022`

**Model/lens:** identical pinned Qwen3.5/J-lens pair to E0002-R5.

**Executed changes from R5:**

1. replaced confounded free generation with forced-choice continuation likelihood;
2. allowed multiple single-token lexicalizations of the same hidden bridge rather than forcing English-only decoder labels;
3. retained the same four hidden country bridges across English, German, and Thai.

**Result:** 12/12 cases evaluated; overall behavioral accuracy 9/12 (75%). J-lens best hidden-bridge rank beat vanilla in 12/12.

| Language | Behavior | Median behavior margin | Median J-lens best rank | Median vanilla best rank |
| --- | ---: | ---: | ---: | ---: |
| English | 4/4 | +2.155 | 1 | 35.5 |
| German | 4/4 | +3.116 | 1 | 41 |
| Thai | 1/4 | -1.172 | 25 | 9405.5 |

Concept-level tension is informative:

- **Canada:** behaviorally correct in all three languages, but Thai hidden-bridge rank was 446;
- **Japan:** hidden bridge ranked 1 in all three languages, but the Thai downstream cloze was wrong;
- **France:** English/German hidden rank 1; Thai rank 22 and Thai downstream cloze wrong;
- **Germany:** English/German hidden rank 1; Thai rank 28 and Thai downstream cloze wrong.

**Interpretation:** English and German are simultaneously behavior-valid and strongly observable for all four bridge concepts. Thai remains a valuable stress condition but currently mixes weaker task competence with weaker/noisier bridge readout. It should not gate proof that the causal apparatus works in languages where both prerequisites are present.

**Decision:** promote an **English↔German causal cross-language smoke** on the same Qwen3.5/lens pair. Do not yet claim a three-language shared Neuralese representation. Thai returns immediately after causal transfer is established and can then distinguish representation failure from downstream-language/task failure.

## E0002-R7 — Qwen3.5 English/German causal hidden-bridge write

**Workflow run:** `35057192234`

**Artifact ID:** `10431580456`

**Artifact SHA-256:** `fbeb040369833dcf5390c56435a9f49967e85c57a0ea1eb9f211a11bd3f7437b`

**Model/lens:** identical pinned Qwen3.5/J-lens pair to E0002-R5/R6.

**Executed:** eight behavior-valid cases: four hidden country bridges × English/German. The same canonical **English** J-space token coordinate was used in both languages, so German received no language-specific latent-address retuning. Four fixed source→target swaps were tested:

- France→Canada;
- Canada→France;
- Germany→Japan;
- Japan→Germany.

For every case the intervention edited prompt positions only; teacher-forced answer tokens were never patched. Conditions were:

- clean baseline;
- J-space coordinate swap at layers 18–22;
- identical coordinate swap at layers 0–4;
- layers 18–22 with a deterministic norm-matched random displacement.

**Baseline:** 8/8 source capitals selected correctly.

**Results:**

| Condition | Strong target-capital switches | Pairwise preference flips | Mean target-minus-source margin change |
| --- | ---: | ---: | ---: |
| J-space layers 18–22 | 4/8 | 4/8 | +4.712 |
| J-space layers 0–4 | 4/8 | 4/8 | +5.704 |
| norm-matched random, layers 18–22 | 0/8 | 0/8 | +0.366 |

The late-band strong successes were:

- Canada→France in English;
- Canada→France in German;
- Germany→Japan in English;
- Japan→Germany in German.

Thus **Canada→France transferred strongly across both languages using exactly the same latent coordinate pair**. France→Canada moved the target margin substantially in both languages but did not cross the decision boundary. The other two directions were asymmetric across languages.

Per-case inspection showed that the early-band effect was itself target-semantic rather than random: for example Japan→Germany flipped the English Osaka case to Berlin early while the late band did not, whereas Germany→Japan flipped the English Munich case to Tokyo late while the early band did not.

**Interpretation:** this is the first strong causal evidence in this program that a specific J-space concept-coordinate write can redirect a hidden intermediate and downstream answer, including one bidirectionally observed **same-address cross-language transfer direction** (Canada→France across EN/DE). The norm-matched random control did not reproduce any strong or pairwise flips.

However, the planned `late workspace` localization hypothesis is not supported: early-layer writes were at least as influential in aggregate. That does **not** falsify latent addressability; it falsifies the narrower assumption that the usable country representation is writable only in the late observer-selected band. A writable latent interface may span multiple stages or early edits may propagate into later computation.

**Decision:** do not tune a late band to rescue the workspace-localization story. The next earned falsifier is **target specificity**: for each source bridge, write each alternative country coordinate and test whether downstream probability moves specifically toward that target country's capital rather than merely away from the source. Run the same matrix in English and German using the same canonical latent addresses. Preserve early and late bands as separate writable-stage conditions; random displacement remains a corruption control. Thai stays held out until target specificity is established.

## Current promotion gate

1. Run a 4-country × 3-alternative-target × 2-language target-address matrix on the already behavior-valid English/German bridge cases.
2. A useful latent address must preferentially move output toward the **chosen target's** capital, not merely suppress the source capital or promote arbitrary alternatives.
3. Compare early and late writable stages descriptively; do not require late-only effects.
4. If target specificity transfers across English/German, apply the exact same canonical coordinates to Thai **without retuning**.
5. A candidate reaches the next `addressable Neuralese` evidence grade only after target-specific cross-language writes survive random/unrelated-target controls and then reuse the same latent address in a second downstream function (for example language/currency/continent rather than capital alone).
