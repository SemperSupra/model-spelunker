# R8 — Mixed interactive/batch real inference, public CPU

This experimental workcell is a *child of PR #332* (reuses its streaming_probe.py direct Ollama client, pinned model digest, fail-closed loopback URL checks and host fingerprint). Authority is [RDTE #316](https://github.com/SemperSupra/model-spelunker/issues/316); parent #306 and configured-actor task validation #139 remain separate.

**Question:** With the backend configured for **two parallel request slots**, when two longer batch requests start before an interactive request, does application-level client admission reserve responsive capacity at the cost of batch makespan?

**Treatments:** `burst2_then_interactive` launches two batch requests immediately and one interactive ~200ms later; `soft_reserve1` launches one batch and one interactive after ~200ms, and starts the second batch only after the interactive completes. This deliberately conservative *client* soft-reservation is not GPU preemption or a physical server slot reservation. Three randomized paired blocks, using unique cohort numbers, identical prompt/token patterns, no real user data; all final token counts and statuses are independently inspected in the workflow.

**Metrics:** first nonempty streamed response elapsed time for interactive request, total three-job wall time, request prefill/decode, prompt and output tokens, exact pinned runtime model digest and public runner CPU/cgroup fingerprint. Any mismatched prompt token counts greater than 5% fail closed. Keep per-trial raw observations and red/blue negative cases.

**Limits:** no agent harness semantic task validation, no real asynchronous tool sleeps, no direct physical KV hit counters, no BigMac/TrueNAS hardware, no hidden production API or secrets, no reliability SLO from n=3 trials. A production interactive reservation cannot be justified until independently demonstrated within actual harness/model/host and privacy/authority gates. Public GHA only, no private minutes.

Run mock tests: `python3 -m unittest discover -s qualification/serving_fanout_r0/mixed_load -p 'test_*.py'`.
