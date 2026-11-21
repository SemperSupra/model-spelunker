# Qwen Code tool-wire isolation — public-synthetic

This branch is **independent** of the batch contract and the real guest boot work. It bisects Qwen's source-neutral agent tool-call transport after the existing [real Ollama/Qwen3 1.7B run failed](https://github.com/SemperSupra/model-spelunker/actions/runs/44873579863).

The fixture starts a fake OpenAI-compatible service **bound only to 127.0.0.1** and launches the official publisher-digest-pinned Qwen Code standalone CLI. The fake provider requests `read_file` on an absolute path to a random 12-byte nonce that is stored exclusively in a disposable fixture file. It only returns the value after the Qwen CLI actually sends a tool-role result. An independent test checks that the tool call and tool result were witnessed and that the final native CLI output matches the hidden file. The server logs no raw prompt, token, host identifier or fixture value. The CI red-team job also tests forged results in user/assistant roles and unsupported tools.

**This is not LLM inference.** The fake model is deterministic and deliberately non-intelligent. Passing the wire oracle means Qwen's CLI/tool/API marshalling works against a minimal OpenAI-compatible SSE provider; it does not prove Ollama, LiteLLM, OpenRouter/DeepSeek, local BigMac/TrueNAS compatibility, multi-agent coordination, memory, MCP authorization, or guest isolation. Its value is to isolate which layer broke without spending a full public CPU model run on every diagnosis.

Independent public hosted GHA jobs: a quick Python standard-library protocol critic and a native Qwen CLI loopback run. Both are public-source synthetic work; they have no private checkout, private source input, credential, outbound model API, production endpoint or administrator privileges. Both have bounded run time and reject an unverified DONE claim.

Upstream Qwen CLI source: `QwenLM/qwen-code@v0.28.3`; the authoritative tested release manifest and packager are inherited from [Model Spelunker PR #221](https://github.com/SemperSupra/model-spelunker/pull/221). Batch policy and small-model actor packet authority remain [#224](https://github.com/SemperSupra/model-spelunker/issues/224). DLE and actual model acceptance live in [#220](https://github.com/SemperSupra/model-spelunker/issues/220) and [#206](https://github.com/SemperSupra/model-spelunker/issues/206).

All smoke work runs in a public disposable runner workspace. No local Windows host changes or production authority.
