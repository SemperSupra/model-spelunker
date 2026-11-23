# R5 independent configured-actor execution baseline

Authority: Model Spelunker #316; configured-actor interview mechanism and task validator: #139; inherited pinned public prebuilt OpenWorker and Ollama workflow. This lane uses **two separate public GitHub Actions runners** launched concurrently, each with its own isolated local Ollama instance. It validates the ability to launch independent workcells and preserve distinct real task evidence with no private GHA minutes, no new agent runner, and no agent-dispatch dependency. IT DOES NOT measure several agents sharing one model server, cache, KV contention, or shared GPU memory.

Real model/harness/tool task success comes only from the child workflow's independent run_task.py deterministic verifier and its immutable run receipt; a successful GitHub workflow can still contain an explicit model task FAIL observation. Do not claim task PASS without examining both child artifacts. Artifacts contain public-safe synthetic task results only. Exact harness artifact sha256, admission_ref and model digest are inherited from the accepted parent workflow.

Follow-on work must compare serialized versus concurrently launched agent tasks with **shared** Ollama process and evidence-backed wall time. This workflow is a control, not a production scheduler.
