# Qwen actor batching contract

**Purpose:** Increase *independently verified completions per iteration* without increasing weak-model context load or spawning a competing execution system. Owner issue: [Model Spelunker #224](https://github.com/SemperSupra/model-spelunker/issues/224). This is a reusable **pure, read-only packet compiler**, not a scheduler, job queue, admission grant, or source of evidence. Agent Dispatch remains the sole executor/admission authority, GitHub DLE remains the sole durable work/source authority.

## Rule for ChatGPT, local Qwen/OpenCode actors and other small models

Never treat the conversation transcript as source-of-truth. Start from the current DLE/AGENTS.md, then read only the exact packet and files it names. Each actor gets **one packet**, disjoint writable paths, one source SHA, one branch, one exact acceptance oracle and short stop/failure instructions. No giant kickoff prompt, unbounded tool exposure, or broad repo scans. A completed edit is not a verified result.

A supervisor plans up to two independent public jobs per batch and collects their evidence **once per round**. It does not wait for an unrelated lane before admitting the next runnable lane; it also does not spin on blocked work, call stalled jobs PASS, or blindly retry unknown-effect operations. If a packet is blocked, record precisely which admission/input/oracle is missing and continue the unaffected packet. Heavy real-guest reps are serialized within their resource pool; fast static/transport/model mocks may run in separate jobs. GitHub Actions concurrency/max-parallel caps are part of the actual resource budget, not an excuse for one-at-a-time agent thinking.

### Small-model cold start (copyable as ONE message)

```text
Read your project's AGENTS.md and the exact authoritative DLE issue in the packet.
Read only one assigned qwen-independent-batches/v1 packet; pin its source_sha.
Check its state, dependencies, resource/credential limits, exact source scope.
Observe -> plan -> only admitted apply in your own branch -> verify against its
independent oracle. Emit SHA, changed paths, test command, result, run URL,
cleanup proof, and next blocker to DLE; stop. Never self-promote, merge,
expand the task, reveal credentials, or run private work on public GHA.
```

### Pure contract commands

```sh
python3 qualification/qwen_batches/contract.py validate
python3 qualification/qwen_batches/contract.py candidates
python3 qualification/qwen_batches/contract.py cards
python3 -m unittest discover -s qualification/qwen_batches -p 'test_*.py' -v
```

`candidates` computes **advisory eligibility only**. It cannot launch jobs, issue credentials, or certify PASS. The two chosen packets are separate isolated branches/jobs; no shared write files. `cards` prints one bounded JSON record per task, suitable for weaker local models with small context. A supervisor may select a single record and use the existing dispatch mechanism *only after* its native grant/lease has been accepted.

### Four independent bands and ownership

- **B01 transport diagnosis:** isolate Qwen CLI vs OpenAI-compatible model protocol in a public loopback mock; exact oracle requires hidden fixture and evidenced tool action. Owns only `qualification/qwencode_wire/`.
- **B02 security red team:** separately test model route classification, forbidden secrets, fallback denial and memory sync. Owns only the pre-existing route compiler; do not collide with B01.
- **B03 Hyper-V guest:** reuse Agent Dispatch's proven public Hyper-V lifecycle and guest builder, not a new VM controller; currently `BLOCKED_ADMISSION` for an exact typed guest-job assignment.
- **B04 sovereign site:** private BigMac/TrueNAS/MCP and local workcell tests, `BLOCKED_ADMISSION`; no private data or credentials in public runners.

Source changes should be split into separate PRs. A batch contract PR must not be merged as a substitute for a failed Qwen tool-call or guest test. `DONE_VERIFIED` requires exact source SHA, independent oracle PASS, and a relevant GitHub run; a machine-readable packet cannot authenticate its own assertions. The existing Agent Dispatch grants and protected reviewer are still mandatory.

### Reps and throughput measurements

At every DLE checkpoint retain `ready`, `in_progress`, `blocked_by_admission`, `blocked_by_input`, `independent_oracle_verified`, `rejected_claims`, `scope_collisions`, `public_GHA_jobs`, `private_GHA_minutes`, and exact head SHAs. Favor `independent verified receipts / public job-minute` and `verified reps / iteration` over volume of commands, agents, or comments. Never infer speedup from merely issuing multiple tool calls simultaneously.

Public sources and CI are safe for source-neutral synthetic Qwen qualification only; real owner hardware, workcell admission and credentials remain private under [IaC #601](https://github.com/mark-e-deyoung/infrastructure-as-code-private/issues/601) and [Agent Dispatch #748](https://github.com/SemperSupra/agent-dispatch-private/issues/748). No new scheduler, public private-repo checkout, unbounded YOLO, or bypass of the exposed LiteLLM-key hold.
