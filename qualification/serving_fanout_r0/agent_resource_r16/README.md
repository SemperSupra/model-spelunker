# R16 — Same-run resource observations for original R6/R7 verified-agent experiment

Authority: Model Spelunker #316, stacked directly on existing [R6/R7 PR #337](https://github.com/SemperSupra/model-spelunker/pull/337). Deliberate sequential dependency: this branch extends the existing R6 runner and its workflow; it does **not** create a second harness runner, validator, model server, router or scheduler. All model/agent/task workload and validator semantics remain as the R6 parent.

## Observation and procedure

- Opt-in environment variable `MODEL_SPELUNKER_RESOURCE_R16=1`, default off. Existing `shared_actor_trial.py` calls a light, unprivileged, stdlib Linux cgroup-v2 observer and includes `phase_resource_r16` in each of the eight original R6/R7 phases. The collector samples `cpu.stat usage_usec`, `cpu.max`, `memory.current`, `memory.max` or an explicitly labeled host-level fallback. It never performs a model request, changes server configuration, or persists prompt/tool/response contents.
- Per-phase reports retain model-independent task validator success from original `qualification/run_task.py`, phase elapsed wall time, bounded process resource observations and observation-source type. The original success semantics are unchanged; no automatic new qualification or routing admission is granted.
- CPU core-seconds and peak instantaneous CPU share use *cgroup* usage deltas. When `cpu.max` is `max`, observed CPU usage divided by visible affinity CPUs is only a proxy; likewise `/proc/meminfo` fallback is a host proxy. Do not mix cgroup used bytes with unrelated host denominator. Missing data is null rather than zero.
- A measured free fraction is only emitted when **both** hard cgroup CPU quota and RAM limit are present, with sufficient samples. Even then it represents observed peak occupancy, not preemptible or guaranteed surge capacity. The field `surge_reservation_guarantee` is always `NOT_ESTABLISHED` pending active admission/failover/fairness testing.
- No nvidia-smi / NVML is installed here, and none of the public CPU results qualify the TrueNAS dual A5000 or BigMac M2 Ultra. IaC #672 holds physical HIL.

## Public free-tier RDT&E

The parent R6 public workflow is re-executed on this stacked branch using **the same** pinned public OpenWorker/Ollama/Qwen task program, exact existing independent task verifier, and eight original serial/parallel/two-wave/burst phases. It additionally checks eight nonempty same-run resource windows without changing tool execution. Independent Linux/macOS source-only unit tests check quota/memory sources, sampled CPU-seconds, missing-vs-zero, counter resets, proxy refusal, mixed sensors and negative windows. All public workflow jobs run in free GitHub Actions; no private GitHub Actions minutes, private source, hosted credentials, or sovereign traffic.

## Analytic limits / next gates

These are same-run resource **observations**, not task-per-joule, wattage or GPU data. No inference request ID is attributed to an individual GPU/KV slot in this CPU experiment. Need compute validation of sampler noninterference, repeated independent runs and controlled perf variance before claiming causal resource savings. Compare verified tasks/hr, CPU core-seconds/task and phase memory pressure only when sensor source is available and matched to task phases. Do not conflate instantaneous headroom with reclaimable hardware reserved for surge.

R16 is a stacked DRAFT, dependent on independent review and eventual disposition of #337. Keep full exact source/runtime/runner SHA and Actions evidence in #316, preserve failures, no merge or production-admission authority implied.