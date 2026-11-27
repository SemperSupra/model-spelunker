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

- Reference mechanisms: #381/#382/#389/#390/#392/#393/#402 are independent experimental source candidates; preserve their exact historical run identities.
- #383 is a mixed-outcome MLX qualification; retain the failed arm and do not merge as an all-pass result.
- #394 is the failed priming parent; #401 is the successful stacked correction. Preserve stack order until an integrated, independently checked source candidate is available. Do not close the parent or flatten away its failure prematurely.
- #403/#404/#407 contain the evolving native contention/retention and shadow-policy experiments. Keep their scopes separate from the runtime and existing workbench/task accounting (#387/#396).
- Product-specific native deployment, free GPU admission, architecture-specific recurrent state, concurrent authorization, and hardware acceptance remain separate, unqualified gates. No production cache manager, routing or infrastructure mutation is authorized by this index.

## R16–R17 evidence and current bake-off lanes

- [#408](https://github.com/SemperSupra/model-spelunker/pull/408) merged: pinned published Mooncake trace replay; [durable results](ish-mooncake-r16.md). Prefix hashes are not session identifiers; results are modeled.
- [#409](https://github.com/SemperSupra/model-spelunker/pull/409): pinned SGLang Simulator CPU. Initial run failed on NumPy/ml-dtypes ABI before cache tests; R17 tests a single compatible resolution. Model forward remains simulated.
- [#410](https://github.com/SemperSupra/model-spelunker/pull/410): native vLLM-Metal host/disk restore passed, 992/1003 reused, exact output. R17 tests declared Torch versus upstream override; dependency metadata mismatch is not silently waived.
- [#413](https://github.com/SemperSupra/model-spelunker/pull/413) merged: actual native llama.cpp RAM pressure and sleep/wake, 15/15 treatments, bounded CPU fixture. [R17 native lifecycle evidence](ish-native-tiers-r17.md).
- Next: published trace adapter to SGLang Simulator; then matched held-out policy/native workload experiments.

For humans and automation, inspect the above PRs, exact run/receipt and source identity before resuming; use existing qualification contracts. The work authority remains [#316](https://github.com/SemperSupra/model-spelunker/issues/316). Use `gh pr checks <number> --repo SemperSupra/model-spelunker` and `gh run view <run-id> --repo SemperSupra/model-spelunker` for current state. Do not replay old one-use admissions or infer success from a queued run.

No release, deployment, automatic retention policy, or hardware acceptance is implied.
