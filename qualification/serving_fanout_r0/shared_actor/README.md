# R6: One Ollama server, two actual configured agents

Authority Model Spelunker #316, existing configured-actor independent verifier #139. Unlike R5 baseline's separate runner per agent, this candidate starts one pinned Ollama 0.34.1 CPU service with OLLAMA_NUM_PARALLEL=2 and executes *both* admitted prebuilt OpenWorker agent tasks against it. Uses qualification/run_task.py as-is for task and evidence validation. No new runner, scheduler, proxy, model registry, deployment or private host access.

Design: two blocks with reversed order, each comparing a serial text-repair+API-boundary task pair with the same tasks concurrently. Four real task phases, eight total task receipts. Every task uses its own disposable workdir and unique output. A GitHub workflow PASS alone is not task success. The driver validates task/harness/model identity, process result, evidence digest and independent verifier result, and preserves all per-task receipts even when the actor's task fails.

Source/model/harness pins must be checked before hydration. Public OpenWorker artifact digest full 64 hex, approved admission link, Ollama archive SHA256, model runtime digest matched to exact expected live tag. Do not infer full Foundry model representation or security policy from runtime tags.

This explores shared CPU-server contention on one public free-tier runner; sample size is tiny, CPU model and task difficulty vary, context warmness carries between phases, no physical KV hit signals, and this does not qualify BigMac/TrueNAS HIL. Fail closed on missing receipt or evidence mismatch. Preserve negatives and do not merge/promote before independent review.
