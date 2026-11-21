# R6-B Qwen3 1.7B model × system prompt length × tool count

[Issue #235](https://github.com/SemperSupra/model-spelunker/issues/235) is an independent child of [batch DLE #224](https://github.com/SemperSupra/model-spelunker/issues/224) and [model-harness qualification #206](https://github.com/SemperSupra/model-spelunker/issues/206). This branch stacks on the earlier [real small-vs-large PR #233](https://github.com/SemperSupra/model-spelunker/pull/233) for source-only reuse, while owning only its own qualification subtree and CI workflow.

The **prior observed control** was a 595-byte streaming OpenAI-compatible request with one read_file tool, real Ollama Qwen3:1.7b, PASS in 5.14s. Its matched large synthetic 29,365-byte / 14,459-system-char / three-tool case timed out at 120.11s. The full Qwen CLI + real Ollama Qwen3:1.7b also failed on similarly large request envelopes with no tools returned. These results suggest a capacity/latency envelope but do not isolate whether bytes, tool complexity or the exact Qwen system prompt are causal.

This experiment defines three independent **real-model** direct-streaming profiles on standard public Ubuntu 24.04 runners, with two-wide maximum concurrency:

| Profile | Synthetic system content | Tool schemas | Independent variable |
| --- | --- | --- | --- |
| `short-three` | short (~104 characters) | read_file, glob, list_directory | tool-count contrast with earlier small/one-tool control |
| `medium-one` | exactly 8,000 fabricated characters | read_file | context-length contrast |
| `medium-three` | exactly 8,000 fabricated characters | same three schemas as short-three | interaction check |

One independent `offline-critics` job proves constant real model name, task prompt, temperature, stream, max output, no private data and non-effectful tool names. Each model job uses **exactly pinned public Ollama v0.34.1 and pinned Qwen3:1.7b SHA** from previous #233 (not a new provider or credentials), and records input bytes, system length, tool count, valid streamed `read_file(file_path=fixture.txt)` selection and wall time. A failed/timeout cell remains failed; the GitHub workflow uses `fail-fast:false` so other cells complete independently.

**Not tested:** actual tool execution, full Qwen Code CLI orchestration, Windows guest installation, hardware host no-taint, sovereign BigMac/TrueNAS models, MCP, YOLO authorization or agent memory. A PASS for a tiny synthetic direct model request is never a full agent PASS. Public GHA uses no private source or credentials; no persistent host tools, no private hosted minutes, no cloud inference key. Do not merge to main or promote a deployment solely from these results.

Command only inside a disposable public hosted job:
```sh
bash qualification/qwencode_envelope_bisect/run.sh short-three
```

For review, use the exact source/run artifacts, not a pasted transcript; an input-model failure classification must retain its negative receipt in #235/#206/#224. The workcell admission gate is external under Agent Dispatch and private IaC #601.
