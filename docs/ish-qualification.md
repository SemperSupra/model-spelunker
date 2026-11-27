# ISH — Inference State Hibernation

*Preserve state. Resume work. Recompute only when necessary.*

This is a public-safe evidence index for [qualification issue #316](https://github.com/SemperSupra/model-spelunker/issues/316), not a runtime installer or release approval. Work authority and outstanding decisions stay in the existing issue; this document is a stable discovery point for reproducible experimental evidence.

## Scope and acceptance

Keep durable logical task state independent of transient model state. Adopt native runtime/cache mechanisms where possible. Exact inference reuse requires compatible model, tokenizer, representation, runtime, cache layout and ownership. Cache equivalence is not task success or exact mid-generation resume. Compare native evaluated-token counts and independently accepted tasks, and distinguish API waiting, storage publication, compute, startup and end-to-end latency. Public CPU/macOS results do not establish physical target, production tenant isolation or accelerator equivalence. Three exploratory reps are screening, not finalist confirmation; see #316 for the existing quantitative gates.

## Stable experimental evidence (R0–R15)

Each row links the exact run and identifies the archive by SHA-256. Historical failed runs and source revisions remain useful negative evidence. GitHub Actions ZIP retention is finite; links and digests alone do not guarantee continued download availability. The tested workflow SHA may be a PR merge SHA rather than its source branch head. Results below are bounded R&D evidence only.

| Workcell | Result and boundary | Run | Artifact ID | ZIP SHA-256 |
|---|---|---|---|---|
| llama.cpp | 3/3 distinct-model A→B→A continuation; 143→4 evaluated prompt tokens | [45417743922](https://github.com/SemperSupra/model-spelunker/actions/runs/45417743922) | 14933990308 | f8e7b1a37de096f540d193f43231a560de8c535b121f858637e0f29304ce4d6a |
| Ollama | Native unload/reload witness; no disk persistence established | [45360972421](https://github.com/SemperSupra/model-spelunker/actions/runs/45360972421) | 14904332817 | 0abaa933d4e43be0f47dcef8191f6c8b526b8898b3a4e735e32177c5f731f503 |
| MLX 256 | Held-out strict cold equality 6/6; selected candidate, not default | [45761285825](https://github.com/SemperSupra/model-spelunker/actions/runs/45761285825) | 15089848496 | d10c6a9027435755a9d00f5865edaaeb6e837775df57f2eb3aff4f36ffd3dae3 |
| MLX 16 | Negative strict cold equality 5/6; all staged/restore comparisons passed | [45761285825](https://github.com/SemperSupra/model-spelunker/actions/runs/45761285825) | 15089748857 | 51b6fd2bb6f8123d0974672d9fae98e48175b62a98329d80d6ae7030026ffcb6 |
| OCI Compose | Disposable runtime, retained external slot state; 3/3 | [45759948573](https://github.com/SemperSupra/model-spelunker/actions/runs/45759948573) | 15089307314 | 405b1153bf04d8688464280022a4c28e276bf18615f77626768a2d9acc05bbaa |
| Native ENOSPC | Actual isolated tmpfs exhaustion, prior committed state restored; not power loss | [45763151642](https://github.com/SemperSupra/model-spelunker/actions/runs/45763151642) | 15090563193 | 500ecfbb04caeb17d9d3d724c952a619a43e0f5c262a76d9b4327e799e587b16 |
| llama-swap | 3/3 automatic pre-eviction save and fenced pre-readiness restoration, 3 negative fallback cases | [45761914598](https://github.com/SemperSupra/model-spelunker/actions/runs/45761914598) | 15089734973 | ccce3a00918471961f4761a986157ab2a3afba4f46336bed289d337e020eae74 |
| Quadlet | 3/3 rootless Podman user-systemd runtime replacement; not native TrueNAS | [45761955015](https://github.com/SemperSupra/model-spelunker/actions/runs/45761955015) | 15090039276 | 64a2b2215adde54e728b9fae4fc32b010a7370b6cd806189cd89da9a8b38ea44 |
| Instruction model | 9/9 exact-code retrieval with corrected one-token priming; no useful-work or speculative-warming acceptance | [45953092253](https://github.com/SemperSupra/model-spelunker/actions/runs/45953092253) | 15178450680 | a33c32bcecca47fac8ed46e3e1a0d9966973949a09c4aa793a25c05d481b6368 |
| Multi-session | 6/6 retrieval; 30/30 fixture ticket rejects; native two-slot concurrency 3/3 | [45955040001](https://github.com/SemperSupra/model-spelunker/actions/runs/45955040001) | 15178158522 | b1eabdd467131ed775f936e189902c4d42c904b5c57b1605f85b409d44f805fd |
| Deferral | 3/3; immediate/deferred API mean 5.126/0.004 s, total disposition 5.168/5.326 s | [46031993756](https://github.com/SemperSupra/model-spelunker/actions/runs/46031993756) | 15215805248 | 5613353fdda417b55bc2d9d417980affa6fa8db58d3f73921badffd1fe761afe |
| Shadow policy | 2,880 screening + 2,880 held-out modeled cells; not observed goodput | [45995266183](https://github.com/SemperSupra/model-spelunker/actions/runs/45995266183) | 15194209914 | 623a58ecf65f86933514a97cc6250f8671ba68be60df6e7e3972f696a9a4bf36 |
| Native retention policy | 54/54 useful synthetic turns, mean complete wall none/LRU/value 77.429/63.500/55.555 s; n=3, supplied prior, all sessions resume | [46032106947](https://github.com/SemperSupra/model-spelunker/actions/runs/46032106947) | 15215691641 | 4c6b7276dead5c4bf1d94d922b6bc67c0449d5d0b155611060880b86e6e6a455 |

Immutable measured cost projections are available at [R11](https://github.com/SemperSupra/model-spelunker/blob/873b6a2c650c665ed85a468a9a78341477f6a37e/qualification/cache_retention_r11/measurements.json) and [R13](https://github.com/SemperSupra/model-spelunker/blob/ed9cd138bf3b5b96733ce121a6a51632ff4650ef/qualification/ish_r13/useful_turn_costs.json). They do not substitute for the full receipts.

## Source and dependency triage

- Merged reference fixtures: #381/#382/#389/#390/#392/#393/#402 (native switching, Ollama residency, Compose, fault recovery, llama-swap, Quadlet, and concurrent restore). Preserve exact historical passing source and receipt identities; none constitutes deployment approval.
- #383 is a mixed-outcome MLX qualification; retain the failed arm and do not merge as an all-pass result.
- #394 failed priming parent and #401 successful correction are closed as superseded by merged #418, whose workflow blob is identical to #401. Preserve both original branches and failed/positive historical receipts.
- #403/#404/#407 merged: bounded deferral, shadow-retention and native policy experiments and frozen cost projections. Keep their scopes separate from runtime authority and existing workbench/task accounting (#387/#396).
- Product-specific native deployment, free GPU admission, architecture-specific recurrent state, concurrent authorization, and hardware acceptance remain separate, unqualified gates. No production cache manager, routing or infrastructure mutation is authorized by this index.

## R16–R20 evidence and current bake-off lanes

- [#408](https://github.com/SemperSupra/model-spelunker/pull/408) merged: pinned published Mooncake trace replay; [durable results](ish-mooncake-r16.md). Prefix hashes are not session identifiers; results are modeled.
- [#409](https://github.com/SemperSupra/model-spelunker/pull/409) merged: corrected SGLang Simulator CPU dependency resolution passed all three upstream tests, including tiered cache accounting. Initial ABI failure retained as negative evidence. Model forward remains simulated.
- [#410](https://github.com/SemperSupra/model-spelunker/pull/410) merged: both native vLLM-Metal dependency treatments passed host/disk restore, 992/1003 reused, exact output. Stable Torch 2.14.0 has clean metadata and is the next experimental baseline; nightly override retains a known metadata exception.
- [#413](https://github.com/SemperSupra/model-spelunker/pull/413) merged: actual native llama.cpp RAM pressure and sleep/wake, 15/15 treatments, bounded CPU fixture. [R17 native lifecycle evidence](ish-native-tiers-r17.md).
- [#414](https://github.com/SemperSupra/model-spelunker/pull/414) merged: deterministic surrogate trace adapter, 192 selected requests and 6,048 pairwise prefix checks; not actual simulator execution.
- [#416](https://github.com/SemperSupra/model-spelunker/pull/416) merged: corrected native SGLang simulator replay completed 108/108 requests and all nine arms. Raw cache attribution verified. Predictor fallback rate 100% in all nine arms; no calibrated latency claim.
- [#417](https://github.com/SemperSupra/model-spelunker/pull/417) remains mixed/failing: R19 seed-only disk isolation and all-case attempts completed; reps 0 and 2 passed both engines; both cold engines failed the same first-answer oracle in rep 1. Preserve negative evidence; no general engine ranking.
- [#418](https://github.com/SemperSupra/model-spelunker/pull/418) merged: exact corrected #401 workflow requalified 9/9; #394/#401 superseded and closed, branches retained.

### R18 verified dependency evidence

| Treatment | Scope | Successful run | Artifact ID | ZIP SHA-256 |
|---|---|---|---|---|
| SGLang CPU | 3/3 upstream tests, clean 231-package metadata, native NumPy/ml-dtypes ABI check | [46073122270](https://github.com/SemperSupra/model-spelunker/actions/runs/46073122270) | 15233624401 | 3a241ab35a095d52fd8709e05126ab44c0272b48b4efac9675bf6c686e38ee7e |
| Metal stable | Torch 2.14.0, clean metadata, exact native host/disk restore | [46073127786](https://github.com/SemperSupra/model-spelunker/actions/runs/46073127786) (declared job only) | 15234161342 | ebc1181b523cd6bc812bd5429e980fc4437e2cc5fe6993285a28e3a979e0a9a4 |
| Metal stable repeat | Same native cache oracle; actual MLX GPU computation | [46073426962](https://github.com/SemperSupra/model-spelunker/actions/runs/46073426962) | 15233822606 | 73466d78dd3f05f808afd25ab3ca28b511739b04c3e7ebece073a1e1572b20c1 |
| Metal nightly override | Same native cache oracle; exact known metadata exception; MPS unavailable on observed hosted device | [46073426962](https://github.com/SemperSupra/model-spelunker/actions/runs/46073426962) | 15233372973 | d3eb1f12dc6a728283c6b855b927c28c8920d7472a6925c96a8fe02b76c6aa76 |

SGLang corrected install: NumPy 1.26.4, ml-dtypes 0.5.3, TVM-FFI 0.1.11, AIConfigurator 0.10.0, pyarrow 25.0.1. Original failed run [46039609103](https://github.com/SemperSupra/model-spelunker/actions/runs/46039609103) artifact 15220600449 (`8192554ad225d1d93b8a4fdf8e9f9cf80aeeab8e657ba032cbc1c1725c576662`) remains a dependency/ABI negative control. Original Metal override preflight failure [46073127786](https://github.com/SemperSupra/model-spelunker/actions/runs/46073127786) artifact 15233816831 (`04f8948dec717f6e498ec0f15407502769a0a25bec93412112936d90d02e3200`) is a distinct MPS capability negative; not a failure of the native MLX cache path. No production lock, cross-host performance parity or physical target acceptance is implied.

### R19 consolidation and negative evidence

Fresh #418 source head `c81ad5bd53f3eedc1f671bd56ad71e62ce727fc7`, [run 46076206721](https://github.com/SemperSupra/model-spelunker/actions/runs/46076206721) PASS 9/9 retrieval, exact cold/restored output, native reuse and restore-count checks. Archive 15235181948 SHA-256 `7e64a4e1729f7f4dddc31811fceccee262b2cdd5961e324652d12df41d56294d`. Main workflow blob `edb713728ff4e0b977b8b006273b9e95c1acfd64` equals #401; merge `28607d7f9ee015d0b17fa78472c9f6db1726dc46`. No failed source promoted.

| Reconciled source | Passing run | Merge |
|---|---|---|
| #381 model switch | 45417743922 | `829093e7447ddb77e93a28c02af4ff4b3acb0a66` |
| #390 fault and ENOSPC | 45763151642 | `4e822e0f7bc281e3e274b37fa14773f2f71903b4` |
| #402 concurrent two-slot restore | 45955040001 | `772d602b98f225fdf4944c1e48a4a3140ada14e3` |

Historical passing archives were independently downloaded and rehashed in R19; source paths are independent public synthetic qualification fixtures, not deployed services. No physical worktree cleanup or destructive branch deletion.

Failed/partial paired MLX/Metal run [46076203384](https://github.com/SemperSupra/model-spelunker/actions/runs/46076203384), archive 15235316560 SHA-256 `e90841aae939d9ecdb665195b66c0733a77cb381c519232db5171610c2b568da`. Rep0 both engines answered correctly; Metal disk reuse included state from the intervening resident reference, so its observed 192-token disk reuse is not a fair first-turn-only comparison. Rep1 failed a cold Metal first answer, not a cache restore; remaining cases were not attempted. R19 tests original cases without lowering quality gates, freezes a seed-only disk store before the follow-up, and collects independent outcomes even after failures.

Simulator replay negative controls: [46076199249](https://github.com/SemperSupra/model-spelunker/actions/runs/46076199249), archive 15235727099 `537e2e06e4f998c15d49830efe5327c23d01ab680d17c40dc349428cb1d54c38` (shallow Git history); [46076252100](https://github.com/SemperSupra/model-spelunker/actions/runs/46076252100), archive 15235102668 `b77ccc3e87da4d7ede88add48d241bce8166ce9258ad30e7799bade30e028879` (spawned child reentered script initialization). Corrected run regenerated all three exact adapter output hashes before failure. Neither proves native published-trace scheduling behavior.

### R20 qualification convergence

| Exact passing reference PR | Run | Merge |
|---|---|---|
| #382 Ollama residency, no disk persistence claim | 45360972421 | `250e3032b49a66913a5b379087dbfbec34e65b28` |
| #389 disposable Compose fixture | 45759948573 | `cec637b86c7fc7d80e2fdf4e31b518f9a42bbda9` |
| #392 llama-swap | 45761914598 | `abd50988961f3e100d06c1464d04385cbd0e7fac` |
| #393 rootless Quadlet | 45761955015 | `09adfa4242ec8425f74e2a5155911dd79475a7ae` |
| #403 deferral and deadline refusal | 46031993756 | `ab035003f50c5a2e22782b16207994bf330b359b` |
| #404 shadow policy with frozen cost projection | 45995266183 | `29dbd8dcd1af24ec670f929297e292965b8ba816` |
| #407 native retention trace with frozen cost projection | 46032106947 | `8b503e067b208a009afc4fcb6795142198f72480` |
| #416 native CPU simulator replay | 46077645481 | `5ec685d609a82d367f083893e4d81b5db98b4f22` |

The seven historical reference archives were independently rehashed and their receipt gates examined in R20. Scope remains public synthetic R&D. Merged cost projections are now discoverable at [R11](../qualification/cache_retention_r11/measurements.json) and [R13](../qualification/ish_r13/useful_turn_costs.json).

**Native simulator published traces.** [Run 46077645481](https://github.com/SemperSupra/model-spelunker/actions/runs/46077645481) PASS, exact head `cf6f0a10aabc5688ac4be4faf98b4fe51d459eb4`, tested merge SHA `3d26754848d38b28c29a9f33603e84ac6d40dadd`, archive 15235329641 SHA256 `4dec4c22c93c209a950869eca78873b2e3ff9d5ba64e3643cd4b125f39bf8ce0`. 12 selected requests per workload and three policies, 108 executions, all nine arm statuses 0. Independently reduce native per-request final hit lengths; final device hit length includes promoted host hits, do not sum overlapping fields as disjoint tiers.

| Workload | Input tokens/arm | None new input | Device new input | Hierarchy new input | Device reuse tokens | Additional host reuse tokens |
|---|---:|---:|---:|---:|---:|---:|
| Conversation | 49184 | 49184 | 43552 | 43552 | 5632 | 0 |
| Tool/agent | 62124 | 62124 | 15020 | 15020 | 47104 | 0 |
| Synthetic | 33905 | 33905 | 31857 | 28273 | 2048 | 3584 |

All input/output counts and tier accounting reconcile across raw 108 request records. Storage hits zero in selected traces (separate upstream storage-tier test passed). All nine arms report zero exact predictor matches and 100% KNN fallback; latency is uncalibrated and must not drive hardware or policy promotion.

**Paired direct MLX/Metal.** [Run 46077441944](https://github.com/SemperSupra/model-spelunker/actions/runs/46077441944) overall FAIL, archive 15236240909 SHA256 `5779b1808fa88a65b08c52f0b41510be6fc46e9fda89076e3260624c0e0b21d0`. All three cases attempted; reps 0/2 pass task and cache gates, rep 1 both cold engines emit 016 instead of 161, so no continuation admitted. Seed-only Metal block reuse 160/205 and 832/877, local compute 45 each; direct MLX submitted suffix 32 for each (not native evaluated-token counter). Preserve quality failure; no general parity or engine ranking.

**Independent confirmation**: [#421](https://github.com/SemperSupra/model-spelunker/pull/421) 12 new native mixed resume/expire cases in four public Linux shards (run 46079403842), supplied priors, exact frozen prior costs, no learned policy claim. [#422](https://github.com/SemperSupra/model-spelunker/pull/422) 12 new MLX 256-step candidate continuation cases in three public macOS shards (run 46079502908), strict cold/replay/live/restore token and top2 gates, no task or physical acceptance. #421 completed all four shards and was consolidated as the bounded native fixture (R21 below); #422 completed and failed the strict cold-equivalence gate: 7/12 exact versus cold, 12/12 repeated cold, 12/12 live/staged-replay versus restored tokens and top-two scores, all submitted suffix lengths 1. Five first divergences involved near ties (including ties); no general exact cold equivalence or task quality claim. #383/#422 mixed outcomes remain unmerged; #417 aggregate quality gate failed. Existing workbench/goodput authorities #387/#396 remain experimental drafts; crossfeed evidence without promoting synthetic continuation into canonical accepted agent work.


**MLX held-out receipts**: run [46079502908](https://github.com/SemperSupra/model-spelunker/actions/runs/46079502908), head `bf43b02adefdd9a22bc2177c25dd052563beedb1`, tested merge SHA `c1f6b274fe6e64631e63f3fe6f6aae3f80cf2ba1`. Three independently rehashed archives: 15235234956 `2081af53c8d21a58ba32a80f45f832c8d62eb7058e0d086a761ac4373a6bf359`, 15237170175 `61b9a9b642381ca2a1840930c4da068858a36e11dfba6f0a362a63aee65bbc5b`, 15237265235 `f7bbe7009e782e8b74024d52464e2cb17ba7a63be1b70ac27be6716deb6b3e34`. Cold context 100–2650 tokens; strict failures reps 1,4,5,10,11. All 12 staged-replay and resident restoration token/top2 witnesses match. Do not select prefill256 for universal strict cold equivalence. Conditional staged continuation remains an exploratory capability, not full-logit or exact sampler/RNG proof.

### R21 independent receipt verification and mechanism diagnosis

**Native held-out retention.** [#421](https://github.com/SemperSupra/model-spelunker/pull/421), exact source head `c0f9dbb0ee1797d8d51b88ade083d0b800081a97`, [run 46079403842](https://github.com/SemperSupra/model-spelunker/actions/runs/46079403842) SUCCESS 4/4 public CPU shards; merge `1898ba7b35fa86916641b3b75a15541997442db4`, exact workflow blob `f255b0a011cf0303fcf9941bd522d95e686e3f60` verified. All four raw archives independently rehashed; [DLE checkpoint](https://github.com/SemperSupra/model-spelunker/issues/316#issuecomment-7229900076) contains the artifact identities and SHA-256 values. All twelve predeclared traces, thirty-six treatments and per-event capacity/expiry/answer/token accounting independently reproduced. 44 MiB cap; peak observed 42,018,788 bytes.

| Policy | Correct synthetic turns | Hits / required resumes | Reused tokens | Newly evaluated resume tokens | Writes | Full lifecycle seconds |
|---|---:|---:|---:|---:|---:|---:|
| None | 53/53 | 0/17 | 0 | 31,924 | 0 | 583.187716 |
| LRU | 53/53 | 8/17 | 16,504 | 15,420 | 36 | 495.280345 |
| Value-aware | 53/53 | 9/17 | 21,583 | 10,341 | 30 | 465.232543 |

Value-aware faster than LRU in 7/12 paired cases. Aggregate lifecycle reduction 20.2% versus none, 6.1% versus LRU. Supplied synthetic priors, no general dominance or learned probability claim. Synthetic accepted turns are not canonical agent deliverables. Nineteen of 36 sessions expire without a required resume per policy; preserve that lifecycle disposition. Existing evidence consumers: [#387](https://github.com/SemperSupra/model-spelunker/pull/387#issuecomment-7229917076), [#396](https://github.com/SemperSupra/model-spelunker/pull/396#issuecomment-7229917519).

**MLX mechanism.** Independently reproduced #422's 7/12 strict cold-equivalence and 12/12 staged/live/restore token/top-two agreement. The five first divergences involve the same candidate pair in each compared path, with reported cold/staged top-two margins 0.0625/0, 0/0.125, 0.0625/0, 0/0.125, 0.0625/0 (reps 1,4,5,10,11). This supports a staged-vs-cold numerical-path investigation, not evidence of serialization corruption. [#424](https://github.com/SemperSupra/model-spelunker/pull/424), head `1fc2bb2698d4fcab576f627d0519dcff841c91a1`, [run 46080848209](https://github.com/SemperSupra/model-spelunker/actions/runs/46080848209) launched three public macOS shards with fixed original contexts, added teacher-forced bulk and serial-tail controls at the same offset, and separate strict parity and diagnostic gates. Execution completed; see R22 below. Preserve #422's negative result and do not infer strict-equivalence qualification from diagnostic completion.

### R22 numerical causality and frozen cost audit

**Mechanism.** [#424](https://github.com/SemperSupra/model-spelunker/pull/424), head `1fc2bb2698d4fcab576f627d0519dcff841c91a1`, [run 46080848209](https://github.com/SemperSupra/model-spelunker/actions/runs/46080848209), all three public macOS jobs SUCCESS, 84/84 planned executions. Tested merge SHA `1bd163187eaf4674f0ebce224d09d285208a8bd9`, consolidated main commit `4cacc0f1f22a0dfbcfde4e994400bc3ae88a6e68`, identical workflow blob `44792b826980f761252a983874601b25517c631e`. [Independent verification and raw archive identities](https://github.com/SemperSupra/model-spelunker/issues/316#issuecomment-7230082563). Cold repeat, staged replay/live/restore, forced bulk vs cold, and forced serial vs staged each agree 12/12 on generated tokens and reported top-two scores. Cold vs staged tokens agree 7/12; reported top-two scores agree 0/12. Failures remain reps 1,4,5,10,11. Same input and offset, different partition reproduces both paths; serialization corruption is not demonstrated. Numerical path is a candidate component of compatibility identity; no full-logit/RNG or universal strict-equivalence qualification. Retain #422 negative evidence.

**Frozen R13 cost audit.** All 12 #421 held-out traces; exact frozen projection `qualification/ish_r13/useful_turn_costs.json` blob `1a7ffcdda1661f1ba3e7f22cea89018737253e99`. Compare sum of frozen net hit benefits minus predicted write costs with paired actual cold-minus-resume request durations less observed restore/write costs; no refitting. See [formula and detailed checkpoint](https://github.com/SemperSupra/model-spelunker/issues/316#issuecomment-7230100316).

| Policy | Projected phase saving (s) | Observed phase saving (s) | Observed full lifecycle saving (s) | Per-case phase MAE (s) |
|---|---:|---:|---:|---:|
| LRU | 99.336926 | 89.093216 | 87.907370 | 0.964500 |
| Value-aware | 131.552675 | 118.039332 | 117.955172 | 1.263758 |

Projection optimistic by approximately 11.5% relative to observed phase savings. Actual write costs 2.867517/2.119702 s versus projected 1.370235/1.107765 s for LRU/value-aware. Full-minus-phase residual -1.185846/-0.084160 s. This is a bounded native synthetic CPU audit, not SGLang GPU calibration or a general error bound.

**Multi-boundary continuation.** [#426](https://github.com/SemperSupra/model-spelunker/pull/426), head `0910b9745e4310ce4c77072872fea6f294c7f562`, [run 46082159775](https://github.com/SemperSupra/model-spelunker/actions/runs/46082159775) initiated on three public macOS shards. Twelve fixed contexts, four execution modes each, 216 planned rejection checks. Verify every receipt, journal, profile and path check against exact source before accepting. Fixture-level rejection is not production authorization or security qualification. Terminal reconciliation completed; see R23 below.

### R23 multi-boundary recovery and architecture-aware qualification

**Native multi-boundary continuation.** [#426](https://github.com/SemperSupra/model-spelunker/pull/426), exact head `0910b9745e4310ce4c77072872fea6f294c7f562`, [run 46082159775](https://github.com/SemperSupra/model-spelunker/actions/runs/46082159775), all 3 public macOS jobs SUCCESS. Tested merge SHA `890987b6b6090d3e733cc39d8364d454cd5bc162`; consolidated main commit `fe328dc5cf0d811f45b70034d9de444699470984`; identical workflow blob `30d72c9f42f3a54941b188c30c944416cbfb297f`. All three ZIP digests, 48 process records, 24 manifest/journal joins, exact staged continuation token/top-two witnesses, offsets and 216 reported fixture rejection labels independently reconciled; see [DLE checkpoint](https://github.com/SemperSupra/model-spelunker/issues/316#issuecomment-7230322588). Twelve contexts, initial input 95–2645 tokens, one exact profile. Raw checkpoint payloads were not uploaded: independent snapshot-byte verification is not established. The in-job native hash check is distinct from the independently verified receipt archive.

| Aggregate phase (12 cases) | Second-boundary restore (s) | Staged reconstruction (s) |
|---|---:|---:|
| Admission / rebuild | 1.757134 | 30.239729 |
| Subsequent generation | 10.795824 | 3.407184 |
| Combined | 12.552958 | 33.646913 |

Second-boundary snapshot publication total 3.456642 s; startup and save excluded from combined row. Do not infer deferred work is absent from API return. No universal cold equivalence, full-logit/RNG, power-loss, authentication or agent-goodput claim.

**Phase attribution.** [#428](https://github.com/SemperSupra/model-spelunker/pull/428), head `c0935f609d297a2f29c1346915ce7169f8b1dfa9`, [run 46083904518](https://github.com/SemperSupra/model-spelunker/actions/runs/46083904518) queued at readback. Fixed 12 contexts, 60 planned native processes, six predeclared permutations of restore/lazy, restore/explicit evaluation and staged replay; separate startup, recover, materialize, first-token and generation phases. No result or cause accepted yet. Retain all adverse outcomes.

**Hybrid source audit.** Exact upstream [llama.cpp a6ac41c](https://github.com/ggml-org/llama.cpp/tree/a6ac41c757c066941766164439f6876f2deaab04): hybrid-memory source blob `a93e256b05a72012d032597425ecbbbe49384b97`, recurrent source `bab6276f65d26cc0ef3d1c6fdafac7c1d08714f4`, Qwen35 source `5b05fc63fdd977c6ca67d5cc6f4964f8850f2b93`, server context `89f884e6548c7fb7282f0e922bd3eacf06322b29`. Native hybrid state writes/reads both attention and recurrent components; server slot files append recurrent checkpoints. Recurrent rollback cannot be presumed equivalent to KV prefix truncation. [Qwen3.5 base model card](https://huggingface.co/Qwen/Qwen3.5-0.8B-Base) documents the hybrid architecture. Proposed public CPU fixture and exact quant digest recorded in #316 R23 claim. Workflow write blocked by a tool safety check; reserved branch `exp/ish-hybrid-r23-316` verified unchanged from `fe328dc5cf0d811f45b70034d9de444699470984`; no job launched and no empirical hybrid result. Existing lifecycle and workbench authorities notified: [#306](https://github.com/SemperSupra/model-spelunker/issues/306#issuecomment-7230339647), [#387](https://github.com/SemperSupra/model-spelunker/pull/387#issuecomment-7230340010).

For humans and automation, inspect the above PRs, exact run/receipt and source identity before resuming; use existing qualification contracts. The work authority remains [#316](https://github.com/SemperSupra/model-spelunker/issues/316). Use `gh pr checks <number> --repo SemperSupra/model-spelunker` and `gh run view <run-id> --repo SemperSupra/model-spelunker` for current state. Do not replay old one-use admissions or infer success from a queued run.

No release, deployment, automatic retention policy, or hardware acceptance is implied.
