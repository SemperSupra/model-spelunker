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

- Merged reference fixtures: #381 (native A/B/A), #390 (bounded fault recovery), #402 (concurrent native restore). Their exact historical passing source and receipt identities remain above. #382/#389/#392/#393 remain independent experimental candidates.
- #383 is a mixed-outcome MLX qualification; retain the failed arm and do not merge as an all-pass result.
- #394 failed priming parent and #401 successful correction are closed as superseded by merged #418, whose workflow blob is identical to #401. Preserve both original branches and failed/positive historical receipts.
- #403/#404/#407 contain the evolving native contention/retention and shadow-policy experiments. Keep their scopes separate from the runtime and existing workbench/task accounting (#387/#396).
- Product-specific native deployment, free GPU admission, architecture-specific recurrent state, concurrent authorization, and hardware acceptance remain separate, unqualified gates. No production cache manager, routing or infrastructure mutation is authorized by this index.

## R16–R19 evidence and current bake-off lanes

- [#408](https://github.com/SemperSupra/model-spelunker/pull/408) merged: pinned published Mooncake trace replay; [durable results](ish-mooncake-r16.md). Prefix hashes are not session identifiers; results are modeled.
- [#409](https://github.com/SemperSupra/model-spelunker/pull/409) merged: corrected SGLang Simulator CPU dependency resolution passed all three upstream tests, including tiered cache accounting. Initial ABI failure retained as negative evidence. Model forward remains simulated.
- [#410](https://github.com/SemperSupra/model-spelunker/pull/410) merged: both native vLLM-Metal dependency treatments passed host/disk restore, 992/1003 reused, exact output. Stable Torch 2.14.0 has clean metadata and is the next experimental baseline; nightly override retains a known metadata exception.
- [#413](https://github.com/SemperSupra/model-spelunker/pull/413) merged: actual native llama.cpp RAM pressure and sleep/wake, 15/15 treatments, bounded CPU fixture. [R17 native lifecycle evidence](ish-native-tiers-r17.md).
- [#414](https://github.com/SemperSupra/model-spelunker/pull/414) merged: deterministic surrogate trace adapter, 192 selected requests and 6,048 pairwise prefix checks; not actual simulator execution.
- [#416](https://github.com/SemperSupra/model-spelunker/pull/416): bounded published-trace replay through the qualified native simulator. Initial shallow-checkout failure corrected; exact adapter outputs regenerated. Second attempt failed at multiprocessing spawn because the test entrypoint ran again in worker processes. R19 adds main guard, import preflight and per-arm result collection; no simulator replay acceptance yet.
- [#417](https://github.com/SemperSupra/model-spelunker/pull/417): same-host direct MLX versus Metal. R18 first matched case passed, second failed cold Metal first-answer oracle (016 versus 161). R19 isolates seed-only disk state from later reference work and attempts all cases independently. Preserve quality failures and do not infer engine ranking.
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

For humans and automation, inspect the above PRs, exact run/receipt and source identity before resuming; use existing qualification contracts. The work authority remains [#316](https://github.com/SemperSupra/model-spelunker/issues/316). Use `gh pr checks <number> --repo SemperSupra/model-spelunker` and `gh run view <run-id> --repo SemperSupra/model-spelunker` for current state. Do not replay old one-use admissions or infer success from a queued run.

No release, deployment, automatic retention policy, or hardware acceptance is implied.
