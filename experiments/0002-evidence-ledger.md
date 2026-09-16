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

## E0002-R8 — paired source/J-space/raw/random falsification controls

**Workflow run:** `35063115753`

**Artifact ID:** `10433870065`

**Artifact SHA-256:** `19e8b977bce8c95632b0ddf63723fc3de3ed618057af601e7843eb7b778b07d7`

**Model/lens:** same pinned Qwen3.5/J-lens pair as E0002-R5–R7.

**Executed:** the same eight EN/DE behavior-valid source→target cases from R7, now with additional falsifiers:

- actual-source J-space swap;
- an absent/unrelated source coordinate (` piano`) to the same target;
- raw residual/unembedding-direction swap with matched source/target semantics;
- deterministic norm-matched random displacement;
- early and late J-space bands retained separately.

**Results:**

| Condition | Target-specific | Strong target switches | Mean intended-target gain |
| --- | ---: | ---: | ---: |
| late J-space | 8/8 | 4/8 | +2.883 |
| early J-space | 8/8 | 4/8 | +2.939 |
| late raw residual | 8/8 | 3/8 | +2.086 |
| late random | 1/8 | 0/8 | -0.645 |
| late absent-source | 0/8 | 0/8 | -2.244 |

Pairwise control comparisons:

- actual-source J-space beat absent-source target gain in 8/8 cases;
- actual-source J-space beat norm-matched random in 8/8;
- J-space beat the raw residual direction in 7/8;
- mean J-space advantage over absent-source was +5.126 target-logprob points;
- mean J-space advantage over raw was +0.796;
- mean J-space advantage over random was +3.527.

**Interpretation:** the effect cannot be explained by merely writing any source coordinate or by generic norm-matched corruption. Raw semantic residual steering is itself effective, so J-space is not uniquely privileged, but J-space usually adds causal leverage beyond the raw direction. Early and late J-space writes remain similarly effective, so no late-only workspace localization is supported.

**Decision:** paired-control apparatus passes its promotion rule. Advance to the all-target EN/DE specificity matrix without changing the latent addresses or intervention method.

## E0002-R9 — full EN/DE target-address specificity matrix

**Workflow run:** `35063516547`

**Artifact ID:** `10433127488`

**Artifact SHA-256:** `81e399d542011db87c4f5049cd8eaf6136be041b8942ab97eb94ae03825c3a5e`

**Executed:** all 24 source→alternative-target pairs over the four country concepts in English and German. Canonical English country coordinates were unchanged across both languages. Each source case was behavior-valid before intervention. Early J-space, late J-space, and late norm-matched-random conditions were retained.

**Baseline:** 8/8 source cases behaviorally correct.

**Results:**

| Condition | Target-specific writes | Strong target switches | Mean target-specificity margin | Mean intended-target gain |
| --- | ---: | ---: | ---: | ---: |
| late J-space | 24/24 | 13/24 | +2.588 | +2.929 |
| early J-space | 24/24 | 12/24 | +1.948 | +2.650 |
| late random | 5/24 | 0/24 | -0.548 | -0.384 |

Every one of the 12 semantic source→target directions was target-specific in **both English and German** under both early and late J-space writes. Late-band strong answer switching occurred across both languages for Canada→France, Canada→Germany, Germany→France, and Japan→France. Other directions often moved the intended target most strongly without always crossing the final answer boundary.

**Interpretation:** this is substantially stronger than source suppression. The written country coordinate selects the intended downstream capital across all tested source/target directions and both prompt languages, while random displacement does not. The effect remains distributed across early and late writable stages.

**Decision:** target specificity has earned two stress tests: unchanged-address reuse in Thai, and reuse of the same country addresses in a second downstream function.

## E0002-R10 — Thai unchanged-address stress test

**Workflow run:** `35063935111`

**Artifact ID:** `10433442919`

**Artifact SHA-256:** `1c69ee32a4417c78bdc20467070dd1d0da3b33673ebc6ff491a552ffcf7eb553`

**Executed:** the same canonical English country coordinates and same all-target causal apparatus were applied to the four Thai bridge prompts with no Thai-specific retuning.

**Baseline:** only 1/4 Thai source cases was behaviorally correct, matching the earlier R6 weakness.

**Results:**

| Condition | Target-specific writes | Strong target switches | Mean specificity margin | Mean intended-target gain |
| --- | ---: | ---: | ---: | ---: |
| late J-space | 6/12 | 0/12 | -0.041 | -0.016 |
| early J-space | 5/12 | 0/12 | -0.035 | -0.046 |
| late random | 3/12 | 0/12 | -0.069 | -0.039 |

For the sole behavior-valid Thai source (Canada), late J-space was target-specific for Canada→France and Canada→Germany but not Canada→Japan; none crossed the output decision boundary.

**Interpretation:** Thai does not robustly reproduce the EN/DE causal-address result under unchanged coordinates. Because the Thai baseline itself is weak, this does not cleanly distinguish representation mismatch from downstream-language/task failure. It is useful negative/stress evidence, not support for a three-language shared-address claim.

**Decision:** keep Thai outside the promotion gate. Do not retune Thai coordinates to rescue the effect; revisit with a stronger multilingual behavioral surface or stronger model only after the EN/DE second-function reuse question is resolved.

## E0002-R11 — ccTLD second-function behavior gate

**Workflow run:** `35064444598`

**Artifact ID:** `10433228131`

**Artifact SHA-256:** `f09d876aaa1c5dc5a8d3035d0b60e847cc46412f244409d9f782a1ebfbe0f14f`

**Executed:** a second downstream function from the same hidden country bridge to country-code top-level domains (`.fr/.ca/.de/.jp`). Causal execution was hard-gated on 8/8 correct EN/DE baselines.

**Result:** behavior accuracy was 7/8 overall: English 4/4, German 3/4. The only miss was German Osaka→`.jp`, where `.ca` won by a very small mean-logprob margin of 0.0201. J-lens still beat vanilla bridge rank in 8/8 cases. Because the behavior gate failed, the causal matrix was automatically skipped.

**Decision:** preserve the 7/8 near-miss rather than prompt-tuning around it. ccTLD does not qualify as the second-function proof surface for this model.

## E0002-R12 — ISO alpha-2 second-function behavior gate

**Workflow run:** `35064888561`

**Artifact ID:** `10433353101`

**Artifact SHA-256:** `0236f95d4c2da32873d201f138fbdc4073175a64594c554fbbe1d4ee45965db2`

**Executed:** a second code-like downstream function from country to ISO 3166-1 alpha-2 (`FR/CA/DE/JP`), again with an 8/8 EN/DE behavior gate before any causal work.

**Result:** behavior accuracy was only 3/8 overall: English 1/4 and German 2/4. Canada was correct in both languages; Germany was correct only in German; France and Japan failed in both languages. J-lens bridge rank still beat vanilla in all 8 cases, but the downstream task was not behaviorally competent. The causal matrix was automatically skipped.

**Interpretation:** the observer can still expose country-related hidden state while the small model fails a code-like downstream mapping. This is exactly why the behavior gate exists.

**Decision:** retire code-like mappings as the immediate second-function route for Qwen3.5-0.8B. The next candidate should be a natural semantic one-to-one function, not another notation/code task. Demonym/nationality is the leading cheap candidate because France, Canada, Germany, and Japan remain distinct and it tests a different semantic consequence of the same hidden country.

## Current promotion gate

1. Behavior-calibrate one **natural semantic, one-to-one** second downstream function over the same four countries and EN/DE prompts. Require 8/8 clean baselines; do not tune the country coordinates or intervention method.
2. If the behavior gate passes, run the same 24 source→target J-space matrix on that downstream function, retaining early/late stages and norm-matched-random controls.
3. The same canonical English country addresses must preferentially move the second function toward the selected target in both English and German. A second-function pass is required before using the phrase `reusable addressable concept coordinate` without qualification.
4. Thai remains a stress condition, not a promotion gate, until its baseline task competence improves.
5. Do not add more observer types, languages, models, or governance until they answer a specific falsification question that the current apparatus cannot answer.
