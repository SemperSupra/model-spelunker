# R11 experimental prompt conditioner: direct task-quality screening

DLE: [Model Spelunker #316](https://github.com/SemperSupra/model-spelunker/issues/316), #139 original configured-agent validator authority, #306 hierarchical memory coordination. This is an incremental part of R9 PR #349 and reuses exact admitted public OpenWorker/Qwen3:1.7b workflow. No new prompt engine, external memory system, agent runner, routing gateway, persistent storage, or credentials.

R9 no-hint reference [public run 45192728599](https://github.com/SemperSupra/model-spelunker/actions/runs/45192728599) showed 0/2 hidden-task passes: boundary-bugfix-v0 stopped without any tool calls, and DLE recovery called listing/reading tools but never wrote its answer. R11 tests two **new exact configured actor treatment tuples**:
- `boundary-bugfix-v0` + existing `inspect-before-claim-v1` hint;
- `dle-cold-start-recovery-v0` + repository-pinned `memory-recall-v1` (≤2048 bytes allowlisted advisory, source-bounded under `qualification/adapters/learning_treatment.py`). The bundle explicitly must NOT change authority, privacy, task instructions, write paths or release decisions.

Both use unchanged original deterministic/hidden verifiers and exact pinned model+harness+task bytes; each job runs on a separate free public runner. Structural source checks execute before model hydration. Record actual verifier PASS/FAIL, tool usage, token cost, output and failure class; CI job SUCCESS is not a task PASS.

Scientific caution: R11 differs from R9 by hint but also runs on different ephemeral CPU nodes and different order/time, with one rep per condition. Any apparent improvement or regression is a **screening result**, not a statistically qualified causal treatment effect. Later paired same-run mixed blocks, exact prompt budget, and additional reps would be necessary before adopting a conditioner. No private GHA spend or production routing.
