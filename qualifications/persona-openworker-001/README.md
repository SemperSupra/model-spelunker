# OpenWorker persona portability canary

Purpose: test whether the two logical personas already exercised through smolagents can be realized through OpenWorker without changing the controller model, mission tasks, bounded tool semantics, authority envelope, or independent oracles.

This is the canonical portability lane, not an OpenWorker-native optimization lane.

Pinned framework:
- `andrewyng/openworker@5bc10d928e0b64aae74313349a3b17bd19643ae2`
- `TurnEngine`
- `OpenAIProvider` pointed at Ollama's local OpenAI-compatible endpoint
- `ToolRegistry` containing only the bounded tools named in `qualification.json`
- `PermissionEngine` in bypass-approvals mode; this does not grant extra capability because no shell/network/general filesystem tools are registered

Controller:
- Ollama `0.34.0`
- `qwen3.5:4b`
- expected resolved ID prefix `2a654d98e6fb`
- temperature 0, max output 768, context 4096

Workloads/oracles are unchanged from the supported smolagents Qwen3.5 canary:
- RTL `popcount4` -> `iverilog` + exhaustive 16-vector testbench
- benign binary unlock -> fixed executable oracle

Two repetitions per pairing are retained so the acceptance condition remains directly comparable: at least one pass per workload.

The runner also captures the local Ollama manifest and layer identities from the same model pull. That evidence is observational and is intended to feed Model Artifact Foundry candidate preparation without a second public 3.4-GB model download.

No specialist model, additional framework, network tool, arbitrary shell tool, or new qualification schema is introduced here.
