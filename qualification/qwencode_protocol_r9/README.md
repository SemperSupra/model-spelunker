# Qwen Code v0.28.3 OpenAI request and SSE usage protocol bisect (R9)

Authority: [Model Spelunker #248](https://github.com/SemperSupra/model-spelunker/issues/248), [batch DLE #224](https://github.com/SemperSupra/model-spelunker/issues/224) and [model qualifications #206](https://github.com/SemperSupra/model-spelunker/issues/206). Branch stacked on [the previously qualified native Qwen CLI synthetic tool-wire PR #226](https://github.com/SemperSupra/model-spelunker/pull/226) to reuse its immutable Qwen v0.28.3 public standalone, file-read oracle, deterministic fake provider and no-private-source policy.

## Why this is necessary

Actual native Qwen Code v0.28.3 + CPU-local Ollama/Qwen3:1.7b **failed** source-fixed hidden-file tool execution in public [run 44880291421](https://github.com/SemperSupra/model-spelunker/actions/runs/44880291421), despite the same model successfully generating direct OpenAI-compatible synthetic tool calls. A separately downloaded digest-checked Qwen3:4b-instruct tier also **failed** [run 44880653775](https://github.com/SemperSupra/model-spelunker/actions/runs/44880653775): five 12,372-byte upstream requests, two schemas, zero tool deltas, terminal `NO_RESPONSE_TEXT`. Model parameter count or byte length alone is not accepted as root cause.

**Upstream official tag/source pins** `QwenLM/qwen-code@99fcf89892f1a3a8027c75468546c7e7be906245` (v0.28.3) and Git blobs in `upstream-pins.json`:
- OpenAI content generator `pipeline.ts` emits `stream_options.include_usage=true` for streaming, normalizes reasoning parameters depending on provider profile, implements output-budget controls and conditional forced tool_choice, and calls `openaiRequestCaptureContext` **after** provider transformations. The direct canaries used simplified requests and did not test all these fields.
- `requestCaptureContext.ts` exposes a source-level exact post-provider request hook; never log raw prompt, headers, tool args or nonce. The SSE tool-call parser supports partial chunks. The upstream chat loop explicitly raises `InvalidStreamError(..., NO_RESPONSE_TEXT)` for exhausted stream attempts without usable progress.

## Two independent free public GHA bands

1. **Source-frozen static contract**: checks all four official upstream Git blob SHA1 identities and required request-construction signals, rejects mutated commits/source, and tests fake SSE positive/negative cases.
2. **Actual native Qwen CLI × deterministic loopback OpenAI SSE provider**: a synthetic provider emits structured `read_file` tool call, finish_reason and a **trailing `choices:[]` usage-only chunk** when requested via `stream_options.include_usage`. The official hash-pinned Qwen CLI must execute the real local file read and return a hidden randomized nonce. A PASS proves synthetic OpenAI stream/usage handling, **NOT inference from real Ollama or model knowledge**.

Both source and fake fixture are public-only, bounded to standard disposable public Ubuntu 24.04 GHA at max parallel 2; source checkout pinned SHA, no secrets, private repo, external model API, persistent host tools, physical Windows changes, SSH, or private hosted Actions minutes. A failure is retained rather than automatically retried or mislabeled successful. Do not allow a test-only fake provider to become a production bridge or authority.

**Expected follow-up if these tests pass:** compare sanitized actual outgoing Qwen request field names and SDK/pipeline finish/usage metadata with the exact direct Ollama canary, varying one field at a time. In particular, `stream_options.include_usage`, reasoning-profile normalization and tool choice. This is a hypothesis, not a demonstrated source of the native failures. No bulk CPU model tier fanout until this protocol ambiguity is resolved.

Keep draft and DLE holds: actual Qwen in admitted booted Windows guest H2, private BigMac/TrueNAS/MCP model routes, exposed LiteLLM #558 rotation, and Agent Dispatch signed workset admission are all separate and currently NOT_ACCEPTED.
