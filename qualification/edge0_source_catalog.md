# Edge0 publisher catalog: source-first model × runtime × agent qualification

**Owning DLE:** [Model Spelunker #206](https://github.com/SemperSupra/model-spelunker/issues/206) and configured-actor interview [#139](https://github.com/SemperSupra/model-spelunker/issues/139). **As observed:** 2026-11-21. This is a **bounded, public-source advisory candidate census**, NOT a new registry, package lockfile, scoring authority, release, or successful interview. The only acceptance authority remains the independently operated task verifier and existing admission workset.

## Source evidence and independent status

Catalog enumerates the publisher's [21 Edge0 Hugging Face repositories](https://huggingface.co/Edge0/models): six text checkpoint variants (four current 120B/145B quantized folders and earlier 8B/35B previews) and fifteen audio ASR/TTS repositories, including ONNX/int8/int4/ANE deployment variants. Exact source paths, current upstream documentation Git blobs, and candidate parameters are in [edge0_source_catalog_v1.json](edge0_source_catalog_v1.json). **A package tag like `0.1B` may not equal the actual underlying parameter count.** Unknown is not zero. Different checkpoint formats and sizes are not independent model architectures.

**Measured by our project:** 8B preview model SHA `269b9a2c4a69d897c50e9f4e125328481d7c0fcf`, public M1 free GHA hydrated ~4.6 GB and started `mlx-lm` HTTP; generation failed HTTP 404, including absent model ID. Zero accepted model answers or Edge0 coding tasks. Synthetic source-only Linux/M1 probes passed. No 35B/120B/145B or Audio8 model-backed task receipt exists here. Vendor or Hugging Face examples are not independent qualification.

| Model | Total/active parameters | Quantization | Published checkpoint weight | Supported engine | Public free-tier disposition |
| --- | --- | --- | --- | --- | --- |
| Edge0-8B-A1B-preview | ~7.9B / ~1.2B | int4-affine G64 + LoRA/prerouter | 4.55 GB (decimal) | older MLX preview, 8B unified native later | M1 isolated HTTP/native source diagnosis; NOT agent qualified |
| Edge0-35B-A3B-preview | ~35B / ~3B | int4 + LoRA/prerouter | 19.6 GB (decimal) | `edge0-infer` native | Source/compile + M1 RAM/disk capacity gate before one generation; NOT RUN |
| Edge0-120B-q3k | 120B / 8.64B | Q3_K+IQ4_NL mixed | 27.98 GiB | `edge0-strata` (CUDA13/Metal) | source/compile only on standard free hosted; model-backend HOLD |
| Edge0-120B-NVFP4 | 120B / 8.64B | NVFP4 | 32.96 GiB | `edge0-strata` | source/compile only; model-backend HOLD |
| Edge0-145B-q3k | 145B / 10.12B | Q3_K+IQ4_NL mixed | 40.81 GiB | `edge0-strata` | source/compile only; model-backend HOLD |
| Edge0-145B-NVFP4 | 145B / 10.12B | NVFP4 | 47.79 GiB | `edge0-strata` | source/compile only; model-backend HOLD |

Never treat `active parameters`, weight bytes on storage, peak working-set memory, and full effective KV/context budget as interchangeable. The 145B/120B model cards advertise up to 256K context, but a free-tier hosted runner has not independently qualified any such long context or CUDA environment. Upstream published performance on larger cards is **vendor evidence**; actual 16/20 GiB VRAM/RAM measurements cannot be extrapolated to free M1 7 GiB. The release's native `edge0-infer` supports 35B, not yet 8B; the 120/145 family requires a separate backend.

## Audio role catalog (15 distinct repositories)

ASR: `Audio8-ASR-Infinite` (continuous streaming), `Audio8-ASR-0.1B` (~0.3B actual params), `Audio8-ASR-0.1B-iOS-ANE`, `Audio8-ASR-0.1B-onnx-runtime`, `ark-asr-0.6b-int8-onnx`, `ARK-ASR-0.6B`, `ARK-ASR-3B`. TTS: `Audio8-TTS-Realistic-Air` (~0.6B), `audio8-TTS-0.1B-ONNX-INT8`, `Audio8-TTS-Preview-0.6b`, `Audio8-TTS-Preview-0.1b` (~0.2B actual), `Audio8-TTS-Preview-0.6B-ONNX-INT4`, `GPA-v1.5-onnx-runtime`, `GPA-v1.5`, `GPA`.

Promising **independent public CPU source/HIL cells**: ONNX-INT8 compact ASR and TTS format checks with synthetic/safely licensed original voice, finite buffers and short transcripts. Test exact language pairs (English, German, Thai), p95 latency, word error / phoneme error, speaker similarity only for explicitly authorized voices, and data handling. Speech models are not substitutions for coding agents. **License must be checked per repository:** for example `Audio8-TTS-Preview-0.1b` specifies a revenue-capped custom Audio8 Community License, unlike the Apache 2.0 licenses of some other published Edge0/Audio8 checkpoints. Do not infer blanket commercial permission from catalog membership.

## Framework/harness crossover roadmap, not vendor-compatibility claims

| Harness | Existing independent acceptance | Edge0 pairing status | Useful role |
| --- | --- | --- | --- |
| OpenWorker | Linux x64 admitted pinned artifact, actual Qwen/Ollama task/verifier receipts | Edge0 untested | default controlled generic task/control |
| Goose | Admitted minimal artifact, timed-out Qwen task examples | Edge0 untested | alternate tool-loop/long-horizon critic |
| Codex CLI / codex-exec | Admitted pinned artifact, observed integration/tool protocol failure with Qwen 1.7B | Edge0 untested | code-repair and tool-schema comparison |
| OpenCode V2 | Synthetic event reducer source qualified; live sovereign task not accepted | Edge0 untested | coding, repo manipulation, subagent/critic after CoW |
| Qwen Code | CLI/provider source/transport passed; public Qwen 1.7B headless tool-use timed out | Edge0 untested | independent agent memory/skills and multi-model subagents |
| Pi / Hermes / OpenClaw | Vendor documents local OpenAI-style endpoint examples; no our own Edge0 task-verifier receipts | Edge0 untested | additional lightweight / generalist candidates, subject to source/capability admission |

Do **not** infer framework support from an OpenAI-compatible `GET /models`: require one native generation request, streaming and nonstreaming tool-call canaries, JSON/schema fidelity, appropriate `model` name and chat-template support, permitted file read/write, independent hidden task oracle, context/token budget, bounded egress and receipts. Keep the configured actor unit `task × harness/version × model/quant/hash × engine/version × tool projection × context/memory treatment × substrate × authority`.

## Execute without overcommitting free cloud

**Parallel A — source-only public GHA:** run deterministic catalog check and guarded mutation negatives on standard Ubuntu, compare upstream engine source revision, release artifacts, and license/SBOM without pulling big checkpoints. **Parallel B — Edge0 M1 compatibility:** existing PR #216 owns one HTTP-vs-native-MLX generation discriminator for 8B; no concurrent branch edit or repeated 4.6 GB speculative matrix. **Parallel C — single qualified framework:** choose one agent harness that can pass a synthetic DLE recovery baseline before comparing memory, skills or other models. **Parallel D — sovereign 35/120/145:** an admitted Mac/TrueNAS/HIL actor separately does exact environment/capability/credential preflight, not public Actions connecting to home. **Parallel E — audio CPU:** after model-specific source/license/dependency review, one independently generated synthetic mono audio/transcript/phoneme fixture and small ONNX checkpoint, with exactly pinned hashes and no real voices.

**Stop rules:** No public standard CUDA assumption; no private source or credentials on public GHA; no private hosted Actions minutes; no rate-/cost-uncapped weights or paid fallback; no private model endpoints contacted from a public runner. Every source-only success remains `MODEL_NOT_RUN`. No task/agent promotion from vendor benchmarks or model self-attestation. Observed host resources and model weights are checked at execution time, not inferred from a marketing footprint.

**References:** [publisher source](https://github.com/Edge0-AI/Edge0), [2026 120B/145B source guide](https://github.com/Edge0-AI/Edge0/blob/main/docs/models/edge0-145b.md), [8B guide](https://github.com/Edge0-AI/Edge0/blob/main/docs/models/edge0-8b.md), [HF model index](https://huggingface.co/Edge0/models), [Model Spelunker DLE #206](https://github.com/SemperSupra/model-spelunker/issues/206).
