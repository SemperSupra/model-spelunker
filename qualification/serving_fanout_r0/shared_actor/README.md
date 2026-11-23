# R6: One Ollama server, two actual configured agents

Authority Model Spelunker #316, existing configured-actor independent verifier #139. Unlike R5 baseline's separate runner per agent, this candidate starts one pinned Ollama 0.34.1 CPU service with OLLAMA_NUM_PARALLEL=2 and executes *both* admitted prebuilt OpenWorker agent tasks against it. Uses qualification/run_task.py as-is for task and evidence validation. No new runner, scheduler, proxy, model registry, deployment or private host access.

Design: two blocks with reversed order, each comparing a serial pair of two **identical text-repair-v0** tasks (isolated agentA and agentB workcells) against the same two tasks concurrently. Four real phases, eight task receipts with per-workcell unique output and independent deterministic validation. Every task uses its own disposable workdir and unique output. A GitHub workflow PASS alone is not task success. The driver validates task/harness/model identity, process result, evidence digest and independent verifier result, and preserves all per-task receipts even when the actor's task fails.

Source/model/harness pins must be checked before hydration. Public OpenWorker artifact digest full 64 hex, approved admission link, Ollama archive SHA256, model runtime digest matched to exact expected live tag. Do not infer full Foundry model representation or security policy from runtime tags.

This explores shared CPU-server contention on one public free-tier runner; sample size is tiny, CPU model and task difficulty vary, context warmness carries between phases, no physical KV hit signals, and this does not qualify BigMac/TrueNAS HIL. Fail closed on missing receipt or evidence mismatch. Preserve negatives and do not merge/promote before independent review.

## R7 extension: four actor clients / two server slots

The initial R6 public GHA result [45172050185](https://github.com/SemperSupra/model-spelunker/actions/runs/45172050185) showed 8/8 independent task verifier PASS, a 24.97% combined serial-to-parallel wall reduction across two reversed-order blocks. Hardened follow-on [45172928322](https://github.com/SemperSupra/model-spelunker/actions/runs/45172928322) again had 8/8 PASS and a 27.87% reduction, with checks for exact task package, full model digest and external verifier exit code.

R7 reuses the same admitted harness/model/validator and adds four independently isolated workcells A/B/C/D using the *same* frozen text-repair task. With the server held at two inference slots, compare two consecutive waves of two agents against one burst of four agents in reversed-order blocks. This estimates whether extra harness fan-out beyond physical server slots improves accepted-goodput, hurts individual response time, creates model/tool failures, or merely queues requests. Exactly 24 task receipts are expected across the combined R6+R7 trial. A model task failure remains recorded and must not be inferred from the workflow conclusion.

Evidence is public-CPU, one ephemeral runner per workflow, 2 blocks only, with warm-cache/order and GPU-platform extrapolation explicitly UNKNOWN. No change is made to host services, model routing, Model-Compass, or sovereign worksets.
