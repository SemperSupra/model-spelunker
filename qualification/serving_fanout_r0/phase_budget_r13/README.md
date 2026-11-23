# R13 — Serving phase and reserve characterization

Owner: SemperSupra/model-spelunker#316; stacked on draft PR #332 (R5 streaming).
This is a read-only, public-safe experiment, not a second runner, model registry, router, scheduler, or admission authority.

## Questions and existing contract

The pre-existing R5 streaming helper provides client TTFT/end-to-end time and native Ollama prompt_eval_count, prompt_eval_duration, eval_count, eval_duration and load_duration. R13 uses it to run a 1-vs-2 concurrency crossover with the same pinned Qwen3:1.7b public model. The independent phase_budget.py reducer produces prefill/decode token rates, percentile latencies, aggregate output tokens per wall second, and observed resource high-water marks. All measurements retain native-engine vs client timing distinctions.

Zero-duration engine phases yield UNKNOWN rates, not inferred throughput. Summed engine phase time across simultaneous requests is NOT wall time. SSE chunks are not token counts. No task validator runs here, so independently validated tasks/hour remains null and route promotion stays HOLD.

## Public GHA CPU resource sensor

capture_public_cpu.py reads Linux cgroup-v2 cpu.stat, cpu.max, memory.current and memory.max, with explicitly labeled host/proxy fallbacks. Missing limits and unsupported signals stay UNKNOWN. Hard cgroup limits, where present, provide an occupancy bound for the runner, NOT an assurance that a surge reservation or preemption will be available in the future. This code is stdlib, unprivileged, local, short-lived, and stores no raw prompts or responses.

## TrueNAS and BigMac qualification

For dual RTX A5000 TrueNAS, require cpu,memory,gpu0,vram0,gpu1,vram1, including each GPU independently; never replace per-GPU exhaustion with a host-wide average. Native NVML/nvidia-smi measurements, their scope, sample clock, driver version and process attribution require separately admitted private IaC read-only HIL. Include PCIe/offload, fan/thermal, swap, process queue and model residency in HIL. A resource sample tagged nvml-observed is only a declared provenance class until independent source verification.

For BigMac M2 Ultra/128GB, collect exact llama.cpp request prefill/decode/cache/slot timing plus a separately validated macOS kernel/IOReport process sampler. Metal currentAllocatedSize from an unrelated MTLDevice is not the model server's memory use. Public GitHub-hosted M1/MLX work is a feasibility substitute, not M2 Ultra HIL.

## Running and limits

Test: python3 -m unittest discover -s qualification/serving_fanout_r0/phase_budget_r13 -p 'test_*.py' -v
Real public CPU: python3 qualification/serving_fanout_r0/phase_budget_r13/capture_public_cpu.py --out /tmp/r13-ollama.json --resources /tmp/r13-resource.json
Reduction: python3 qualification/serving_fanout_r0/phase_budget_r13/phase_budget.py --input /tmp/r13-ollama.json --resources /tmp/r13-resource.json --out /tmp/r13-reduced.json --reserve .25 --ttft-slo-ms 3000

The real capture requires preexisting pinned loopback Ollama started by the bounded public Actions job. It contains two exploratory cells only, so it cannot establish a P95 tail SLO, verified task goodput, route admission or operational reserve. Test negative controls deliberately reject fabricated success, missing resources, forged identities, invalid timings and dual-GPU aggregation.

Next gates: add a pinned small public MLX model on M1 with independently measured phase and token events; perform separately admitted BigMac/TrueNAS sensor calibration; join existing #139 independently verified actor/task outcomes and immutable MAF identity for tasks/hour; replicate/crossvalidate before candidate placement. No private GitHub Actions minutes, sovereign traffic, credentials, host restart, deployment, merge or release are authorized by this public work.