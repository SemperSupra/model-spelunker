# Exploratory public-runner Ollama concurrency probe

Authority: [Model Spelunker #316](https://github.com/SemperSupra/model-spelunker/issues/316), parent #306, configured-actor effectiveness #139.

Uses the **existing** pinned public Ollama v0.34.1 archive SHA-256 and Qwen3:1.7b model tag/digest prefix already exercised by `.github/workflows/openworker-ollama-qualification.yml`. The test does not run an agent harness, reuse private prompts, use GPU resources or inspect BigMac/TrueNAS. Only loopback HTTP is accepted.

Distinct conditions: client-side concurrency 1/2/4; two synthetic prompt-prefix arrangements; four requests/condition; three sequential blocked replicates (72 measured requests) with randomized condition order and **unique cohort-specific prefix identities** across conditions; one separate warmup. Verify actual prompt-token parity between prefix treatments; do not compare mismatched treatments. Records server-reported prompt/eval token counts, load/prefill/decode duration, client wall and latency. The runner uses `OLLAMA_NUM_PARALLEL=4` and `OLLAMA_MAX_LOADED_MODELS=1`; thus **client concurrency is varied, server concurrency is held fixed**.

Three blocked replicates on one runner are screening evidence, **not independent host repetitions** and too small for meaningful P95 SLO claims. Real TTFT is UNKNOWN because the endpoint is nonstreaming. The probe does **not** measure KV hit rates, quality-verified tasks, correctness of hierarchical compaction, GPU contention, M2 Ultra performance, or admission policy reliability. Do not compare against any other model/host or approve deployment using this result.

Model digest is recorded in full at runtime, but compared to a historical prefix only; Foundry exact representation, licensing and runtime admission remain UNKNOWN/NOT ASSESSED. Source SHA, runtime and ephemeral CI run ID are part of external GHA evidence. Fail closed on model absence, invalid response metrics or non-loopback target.

Run tests offline: `cd qualification/serving_fanout_r0/real_cpu && go test -count=3 ./...`. The public workflow separately invokes a real Ollama CPU request cohort and uploads its sanitized receipt.

## RED finding from first run (retained)

The initial 24-request [public run 45145650904](https://github.com/SemperSupra/model-spelunker/actions/runs/45145650904) completed direct model requests but **failed scientific comparison eligibility**: the six conditions reused the same prompts, the exact prefixes were progressively cached, and prefix-treatment prompt lengths differed (~270 vs ~337 tokens). Measured condition wall times ranged from 2.4s to 21.4s for four requests, with severe time/order confounding. Preserve this run as a negative-control receipt; never cite it to select a concurrency default. The revised code introduces unique condition cohorts, controlled lexical counts, three randomized blocks and token-parity rejection. Even after correction, server-reported KV cache hit information is unknown and only real hardware/harness work can establish service envelopes.
