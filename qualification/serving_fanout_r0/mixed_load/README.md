# R8 — Mixed interactive/batch real inference, public CPU

This experimental workcell is a *child of PR #332* (reuses its streaming_probe.py direct Ollama client, pinned model digest, fail-closed loopback URL checks and host fingerprint). Authority is [RDTE #316](https://github.com/SemperSupra/model-spelunker/issues/316); parent #306 and configured-actor task validation #139 remain separate.

**Question:** With the backend configured for **two parallel request slots**, when two longer batch requests start before an interactive request, does application-level client admission reserve responsive capacity at the cost of batch makespan?

**Treatments:** `burst2_then_interactive` launches two batch requests immediately and one interactive ~200ms later; `soft_reserve1` launches one batch and one interactive after ~200ms, and starts the second batch only after the interactive completes. This deliberately conservative *client* soft-reservation is not GPU preemption or a physical server slot reservation. Three randomized paired blocks, using unique cohort numbers, identical prompt/token patterns, no real user data; all final token counts and statuses are independently inspected in the workflow.

**Metrics:** first nonempty streamed response elapsed time for interactive request, total three-job wall time, request prefill/decode, prompt and output tokens, exact pinned runtime model digest and public runner CPU/cgroup fingerprint. Any mismatched prompt token counts greater than 5% fail closed. Keep per-trial raw observations and red/blue negative cases.

**Limits:** no agent harness semantic task validation, no real asynchronous tool sleeps, no direct physical KV hit counters, no BigMac/TrueNAS hardware, no hidden production API or secrets, no reliability SLO from n=3 trials. A production interactive reservation cannot be justified until independently demonstrated within actual harness/model/host and privacy/authority gates. Public GHA only, no private minutes.

Run mock tests: `python3 -m unittest discover -s qualification/serving_fanout_r0/mixed_load -p 'test_*.py'`.

## R8a negative outcome and R8b correction — November 23, 2026

First real public CPU [run 45190862336](https://github.com/SemperSupra/model-spelunker/actions/runs/45190862336) successfully executed 3 paired blocks, but **does not permit a clean batch-makespan policy conclusion**. Batch outputs ranged from 33 to 48 tokens even with a 48-token generation cap, while interactive outputs were 8. A surprisingly fast 2.27-second interactive first-token result under burst2 in block 1 also made the direction inconsistent: burst2 TTFT 2.27/26.06/27.69 s vs conservative reservation 10.03/9.73/9.91 s. Preserve the entire negative/exploratory receipt, artifact 14825358569, ZIP sha256 `14bfcd71f4d19d3d4b8cd5e4b1edd197df26c925a9d8468ab15010d9f62c1de5`, and JSON sha256 `b15e3f31416f335d56a4f6e0b0d6e6a4fcfd5436fddaf1dafd338a007e4fa73d`. Observations suggest that client-side deferral is **not** synonymous with a hardware-reserved streaming slot; do not publish this as a reliable scheduler win.

R8b adopts a fixed expected generation budget: 32 output tokens for each long batch and 8 for interactive, with instructions deliberately longer than that budget and **hard rejection** of early EOS or mismatched completion counts. Paired prompt input length must still match within 5%. If this gate fails, retain the result as blocked and redesign, not quietly drop samples or soften admission. Remaining limitations: no independent host replicas, no real model task validation, no measured KV hits, no physical BigMac/TrueNAS performance, and no production-service reliability conclusion.
