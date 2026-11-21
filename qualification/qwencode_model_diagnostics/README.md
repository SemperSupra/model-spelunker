# Qwen Code model-wire capacity bisect — public CPU-only band B05

Parent authority: [Model Spelunker #206](https://github.com/SemperSupra/model-spelunker/issues/206) and [bounded batching #224](https://github.com/SemperSupra/model-spelunker/issues/224).

The official Qwen Code v0.28.3 native CLI successfully performed a real `read_file` through a deterministic loopback synthetic model with a hidden nonce in [wire run 44875274568](https://github.com/SemperSupra/model-spelunker/actions/runs/44875274568). By contrast, the real Ollama/Qwen3 1.7B agent rep [44873579863](https://github.com/SemperSupra/model-spelunker/actions/runs/44873579863) timed out despite a successful *plain-text* direct provider canary.

This independent rep isolates **Ollama/Qwen3 tool selection and SSE**, not Qwen's own agent/harness. It pins the official Ollama 0.34.1 Linux x64 archive to SHA256 `f361dc3992ec07e4ad429f4bb2d10d4663ba2c295f9a9a688c7d52f4ba650034`, verifies the specific Qwen3:1.7b model digest prefix, starts a loopback-only Ollama service on an ephemeral **standard public Ubuntu 24.04 free hosted runner**, and runs two equal tiny prompts with one `read_file` tool definition using `reasoning_effort: none`: OpenAI-compatible non-stream and OpenAI-compatible SSE stream. It records exact whether a valid `read_file(file_path="fixture.txt")` function call was generated in each, whether stream completion or content-only fallback occurred, and a bounded elapsed time. It neither executes the model's proposed tool nor asserts that the actual agent can consume the response.

An independent protocol critic runs as a second public batch: split streamed names/arguments, empty SSE, content-only, invalid arguments, wrong file, unrelated tool and no private endpoint/credential controls.

Interpretation: **both tool calls PASS** narrows the remaining failure toward Qwen agent/harness × prompt size/context × model-runtime interaction; **non-stream PASS / SSE FAIL** implicates the streaming wire or decoding path; **both FAIL** points to local model tool-selection/capacity. All results remain task × model × runtime specific. No synthetic or direct model success promotes the untested sovereign BigMac, TrueNAS, MCP, local Hyper-V or full multi-agent experience.

No private source/credentials, no remote hosts, no public external model API, no self-hosted runner, no host tool installation or new scheduler. The GHA job is an on-demand public-only diagnostic and captures a small bounded sanitized receipt even when it fails.
