# R15 — Independent reduction of actual configured-agent goodput

Authority: Model Spelunker #316, consuming the existing #139 task runner and R6/R7 source [draft #337](https://github.com/SemperSupra/model-spelunker/pull/337). This is an offline **evidence reducer**, not another harness, scheduler, evaluator, or model. All sources public safe. No new model inference is executed.

## Original immutable source

- GitHub Actions run: 45173592480 (public CPU), original artifact ID: 14818028151
- Exact original ZIP SHA-256: 0904c7f87f6e6b2abd2f3124eee2e579d08426a6bbe0b768d0a9532b6a74110e
- Workload source SHA recorded by actual runner: aa0f0144d266492643390742fe0a628283130400
- Model: qwen3:1.7b, exact Ollama runtime digest 8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7
- Harness: OpenWorker exact artifact e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83, existing admission reference frozen in reducer
- Task: text-repair-v0, task-class software.bounded-repair, package digest a51be2ffb8cbe2cacac72f038bb88a1649d491ff853244adb729981c9d6c24cc

## Scientific gate

Reducer rejects missing/extra/duplicate ZIP members, wrong total bytes/digest, wrong model/harness/task/provenance, duplicate task run identity, stale source, malformed independent v1 receipts, contradiction between external verifier status and R6 task summary, missing terminal actor result, implausible time accounting and nonfinite measurements. It derives observed, **short-run** successful tasks per hour from the original verified results divided by *whole phase* elapsed time. Two reversed-order blocks provide only exploratory paired ratios; does NOT claim robust sustained rates or statistical population P95.

Important: This operation validates existing task receipt consistency; it does NOT rerun the independent semantic verifier and does NOT promote the original claim beyond the original task/actor/substrate scope. Positive original task receipts have prior verifier exit code zero, semantic-success, state changed and matched evidence digest. No raw tool output, prompts, or hidden reasoning are exported in derived R15 summary.

## Resource limits and nonjoin rule

R6/R7 task artifacts do not contain matching per-phase physical utilization or reliable reserve measurements. R13 direct-inference phase metrics come from a different runner, prompt configuration and server workload, so combining them to claim configured-agent CPU/GPU resource goodput would be invalid. The reducer explicitly returns null for both reserve and R13 prefill/decode join. In particular this experiment is NOT a BigMac/TrueNAS or GPU qualification; IaC #672 remains the host-read-only authority and HOLD.

## Bounded free public CI

Linux+macOS stdlib negative oracles; a third independent public Ubuntu job downloads the existing GitHub Actions artifact **once** using read-only GitHub Actions permission, verifies original ZIP sha, checks all 24 task v1 receipts, derives eight phase goodputs and four paired comparisons, and uploads only the sanitized derived record. No new Ollama, model, token spending, private Actions minutes, or actor execution. Original artifacts remain held at the prior GitHub run. PR is DRAFT, not a release/merge.

## Next discriminating experiment

Perform a matched same-run configured-agent #139 benchmark with native model phase measurements and calibrated host sensors, at concurrency 1/2/4/8 and in mixed interactive/batch traffic. Join by actual request/trace and immutable runtime/config, then quantify independently verified tasks/hr, tasks per CPU-core-hour, memory/VRAM headroom, queue wait, task correctness, and interactive SLO. Admit host HIL separately. Initial reserve target 25% remains a hypothesis, not hard guaranteed capacity.