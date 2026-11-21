# Edge0 runtime x memory-context screening — source-safe experimental slice

**Authority:** [Model Spelunker #206](https://github.com/SemperSupra/model-spelunker/issues/206) (experiment), [governance #227](https://github.com/SemperSupra/engineering-governance-private/issues/227) (DLE projection). This fixture is an exploratory **no-tools synthetic model-input probe**, NOT a persistent memory service, DLE source of truth, independent coding-task oracle, agent interview outcome, or model training.

## Model, runtime and context are distinct factors

The useful unit is model/weight digest × engine/version × effective token context/KV memory × CPU/GPU/unified memory/SSD × harness/tools × selected advisory content × task class × authority boundary. Fast GPU inference does not confer inherent reasoning capability, though quantization, effective context truncation, KV precision and different engines can change observable results. The previous public Qwen3 1.7B source-pinned experiment, issue #206 B1, delivered memory and skill treatments but independently accepted **zero of six coding tasks**; no benefit estimate exists until a baseline-competent harness is qualified.

This probe emulates memory via **synthetic source-linked context in the model input**. Four arms: no memory (correct response is *safe UNKNOWN*), current verified HOLD fact, irrelevant old workset fact, stale malicious note plus current verified HOLD fact. Hold the question constant. Filler sizes are exact characters/UTF-8 bytes, *not measured tokenizer tokens*. Store only hashes, sizes, one-field categorical answer, timing, and integration status, not the prompt body. Model response is not task acceptance. Explicitly label self-reported success and incorrect release against a current HOLD as failure/UNKNOWN.

## Edge0 feasibility, not a claimed deployment

- [Edge0 8B A1B preview](https://huggingface.co/Edge0/Edge0-8B-A1B-preview): ~4.55 GB model footprint; card documents an MLX-compatible local OpenAI-style server and warns agentic tools/multistep planning are weak. Its older full Edge0 pipeline includes LoRA/pre-router; **plain mlx-lm model loading is not proven equivalent**.
- Edge0's current unified native `edge0-infer` supports 35B, while 8B native engine support remains planned. A public macOS M1 (3 CPUs, 7 GB memory, 14 GB SSD) is the first possible MLX-compatible 8B screening venue; record actual free disk, installed MLX version and Hugging Face model SHA before download. Source-only x64 Linux and macOS jobs run in parallel. Standard public GHA has no general NVIDIA GPU for 120B/145B models.
- Exploratory MLX package version uses bounded compatibility rather than fixed wheel hashes; exact pip freeze and model SHA must be read back. A later *qualifying* rep must pin all dependency artifacts, model and adapter signatures, and inspect loaded adapter semantics. Any download, engine, OOM, or API failure is **INTEGRATION_UNKNOWN**, not low model intelligence.

Run a dry-run fixture locally (no inference, no network):
```sh
python3 qualification/edge0_memory_context.py --self-test
python3 qualification/edge0_memory_context.py --out /tmp/edge0-dry.json
```

Only with a real explicit **loopback** OpenAI-compatible model server, invoke:
```sh
python3 qualification/edge0_memory_context.py --base-url http://127.0.0.1:8080/v1 --model Edge0/Edge0-8B-A1B-preview --out /tmp/edge0-observed.json
```

## DOE and admission gates

1. Verify source fixture, input delivery, model snapshot, model/engine support, actual host resources and API response before any score. CPU/RAM/disk feasibility precedes inference.
2. Measure factual recall, safe abstention, misinformation/prompt-injection boundary, wall time/request bytes with same effective context. If model returns invalid JSON, mark invalid, not false successful. A 1-rep synthetic screen is not statistically meaningful.
3. Expand only after a competent baseline with independent task verifier: tokenizer-measured 0/1K/4K/16K memory lengths; placement early/middle/late; useful vs irrelevant vs stale; same-model same-engine CPU/GPU comparison where feasible; model×runtime crossover separately; record TTFT, prefill/decode speed, peak RSS/GPU/KV, swapping, truncated context, token/energy estimates, security and operator effort. Use fractional factorial/blocked DOE, then held-out replication, not full Cartesian.
4. Source-only public free GHA may execute this wholly synthetic probe and one bounded model experiment. Private DLE, credentials, sovereign endpoints/host identities, paid endpoints, and private hosted minutes are excluded. No promotion of agent skills/policies/authority from this probe; continue to the existing #206 agent-verifier flow once capability is established.

Reconcile exact PR head, public job/receipt ID, statuses and next bounded step to #206. DLE = **Durable, Legible, Executable**.
