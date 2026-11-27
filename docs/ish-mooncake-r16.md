# ISH R16 — Published Mooncake trace replay

Scope: modeled contiguous full-prefix-block reuse; not measured serving latency, task correctness, session ownership, GPU memory, or agent goodput. Source [Mooncake FAST25-release](https://github.com/kvcache-ai/Mooncake/tree/1d0e4c7587b57b78a1997be370b349b79828c5dd/FAST25-release), exact commit `1d0e4c7587b57b78a1997be370b349b79828c5dd`. The replay uses only published anonymized timestamps, token lengths and prefix hashes. Hashes are not session identifiers. Full blocks are keyed by their prefix ancestry, incomplete tails ignored, and an isolated cached descendant is not counted as a hit.

## Evidence

[Run 46039602315](https://github.com/SemperSupra/model-spelunker/actions/runs/46039602315) passed. Exact source head `d86d4acf028b64f93a3f457c0b845e0d5e279017`; tested merge SHA `2b3336932b9589fdd59d0463d5d9cf659c0b5527`. Raw archive 15219802554 independently rehashed: `c5c62f84be4635d8904b5d19368da4715c497d6eef1249f968e3586ab134619b`. Archive expiry does not affect the pinned source or workflow.

| Workload | Total requests | Training | Held out | Trace SHA-256 |
|---|---:|---:|---:|---|
| Conversation | 12031 | 8421 | 3610 | b8cbb061a85206d729d91cdc2981f43c9e0d99209dce588d3af5f7934408b9df |
| Tool/agent | 23608 | 16525 | 7083 | 48a2db1a13d3bc05e6330140c64f604ba366df20d3c9e128b5c35a01c1fa5f71 |
| Synthetic | 3993 | 2795 | 1198 | bd070915a98fc0ed264d7cfef2ce746002eb3076a695ec31ba2674c0111ec131 |

Chronological 70/30 split. Each holdout arm starts cold; frequency policy alone uses frozen counts from training. Each capacity is a count of 512-token blocks, not a device-specific byte capacity. Time in the source is milliseconds. Equal-time events preserve input order. The policies are illustrative block-store policies, not exact native engine eviction implementations.

## Compact result

Reused input tokens as percent of all held-out input tokens. No-cache control 0% in every workload. Rounded to three decimals from the verified raw receipt.

| Workload | Capacity blocks | LRU | LRU + TTL 30s | LRU + TTL 120s | Frozen training frequency |
|---|---:|---:|---:|---:|---:|
| Conversation | 512 | 4.497 | 4.497 | 4.497 | 6.578 |
| Conversation | 2048 | 5.530 | 5.477 | 5.530 | 10.252 |
| Conversation | 8192 | 19.468 | 5.755 | 19.297 | 15.426 |
| Tool/agent | 512 | 36.028 | 36.028 | 36.028 | 37.482 |
| Tool/agent | 2048 | 36.862 | 36.820 | 36.862 | 40.191 |
| Tool/agent | 8192 | 47.548 | 37.014 | 47.093 | 45.155 |
| Synthetic | 512 | 9.179 | 9.179 | 9.179 | 8.357 |
| Synthetic | 2048 | 30.010 | 30.010 | 30.010 | 15.215 |
| Synthetic | 8192 | 62.879 | 42.777 | 62.879 | 53.524 |

All per-arm capacity bounds and token accounting reconcile. Frequency does not dominate LRU; policy ranking varies with workload and budget. Fixed TTL may prematurely evict useful blocks. Do not derive a production TTL, resumption probability, service demand, or goodput from this experiment. Next: native simulator replay and actual inference/agent controls with explicit compatible identity and independently verified tasks.

Execution entry point: [ish-mooncake-traces-r16.yml](../.github/workflows/ish-mooncake-traces-r16.yml). Authority: [#316](https://github.com/SemperSupra/model-spelunker/issues/316).
