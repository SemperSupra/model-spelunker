# Peer Review Dossier & External Evaluation Contract

Authority & Boundary:
- Peer Review Protocol: DLE Structured Peer Critique
- Evaluation Scope: Dual-node sovereign inference architecture (BigMac M2 Ultra + TrueNAS SCALE dual RTX A5000), model routing (`model-compass`), uncensored/heretic model intake, and deterministic local qualification harnesses.
- Return Schema: `schema_version: 1`, `evaluation_type: "peer-review-feedback"`.

---

## 1. System Under Review (Architecture & Implementation)

### A. Infrastructure Topology
1. **BigMac (`192.168.178.105`)**:
   - Hardware: Apple Silicon Mac Studio M2 Ultra (24 CPU cores: 16P + 8E, 76-core Metal GPU, 128 GB Unified Memory).
   - Runtimes:
     - `llama-server` multi-model preset router on port `8080` (Q8_0 KV cache, FlashAttention ON, continuous batching, serving up to **262,144 / 256K context**).
     - `strata` 0.1.65 streaming latent-MoE engine on port `8085` (`Inkling-2-Mini-SQ-10` with DSpark Block-8 drafter and o200k BPE tokenizer).
2. **TrueNAS SCALE (`192.168.178.49` / `.106`)**:
   - Hardware: AMD Ryzen 7 5800X (8C/16T), 64 GB DDR4 ECC RAM, Dual NVIDIA RTX A5000 (48 GB combined VRAM, Ampere GA102).
   - Runtimes:
     - `ollama` v0.40.16 on port `30068` (tuned with 32 GB cgroup RAM, 12 CPU cores, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_SCHED_SPREAD=true`, and 32K context to guarantee 100% GPU layer residency across dual GPUs).
     - `litellm` upstream routing proxy on port `30040`.
3. **Local Workstation (`Windows 11 x64`)**:
   - Execution Layer: `actor-run.ps1` dispatching local CLI harnesses (`aider`, `hermes`, `opencode`, `goose`, `cline`).
   - Router & MCP Service: `model-compass` Go v2.0 binary (`C:\Users\Mark\.local\bin\model-compass.exe`) providing multi-venue health probing, ranked model recommendations, sommelier specials, and tooling dialect hints.

### B. Recent Technical Milestones Completed
1. **Container & KV Cache Tuning**:
   - Diagnosed and resolved Ollama cgroup OOM termination on 70B models and CPU offloading timeouts on 32B models by raising RAM limit to 32 GB and enabling `q8_0` KV cache (reducing KV VRAM consumption by 50%).
   - DeepSeek R1 32B now achieves **29.52 tok/s** (100% GPU resident), Qwen 3.5 9B reaches **88.5 tok/s**, and Qwen 3.8 Uncensored 27B runs at **34.70 tok/s**.
2. **Model Upgrades & Abliterated Deployments**:
   - Deployed surgical uncensored models: `Qwen3.8-27B-Uncensored-Q6_K` (BigMac, 256K context) and `coder3101_gemma_4_31b_it_heretic-Q4_K_M` (BigMac, 128K context).
   - Reconciled intake inventories and SHA-256 cryptographic hashes in `SemperSupra/model-artifact-foundry-private` (`consumer-model-reconciliation-20261123.md`).
3. **Engine Exploration**:
   - Evaluated Basalt runtime (incompatible: Blackwell `sm_120` hardcode).
   - Evaluated and operationalized Strata (`strata-inkling` on BigMac).
4. **Harness Alignment & Router Build**:
   - Developed `model-compass` in Go: exposes MCP stdio protocol (`recommend_models`, `get_venue_catalog`, `get_sommelier_specials`), live health checks, and task-family priority rankings.
   - Enforced sovereign DLE boundaries: adapters fail-close on non-RFC1918 traffic or leaked cloud API tokens.

---

## 2. Peer Review Objectives & Questions

Please review the engineering choices, architectural tradeoffs, and operational risks:
1. **Hardware & VRAM Partitioning**: Is splitting workloads between M2 Ultra (large-context unified memory, 256K) and dual RTX A5000s (high raw compute density, 32K context spread) the optimal boundary?
2. **Harness Routing Strategy**: Direct harness routing to native server ports (stripping reasoning traces with `think: false` for diff generation) vs. routing everything through LiteLLM. What failure modes or blind spots should we anticipate?
3. **Model Selection & Quantization Choices**: We chose `Q6_K` for Qwen 3.8 27B and `Q4_K_M` for Gemma 4 31B Heretic. Are there superior ablation methods or quantization formats for agentic code refactoring?
4. **Telemetry & TCO**: We observed BigMac idling at ~1.9W and TrueNAS dual A5000s idling at ~39.3W (monitoring via Prometheus `node_exporter` and macOS `powermetrics`). What metrics or alert thresholds are missing?
5. **`model-compass` MCP Design**: What additional MCP capabilities or task heuristics should `model-compass` expose to agent harnesses?

---

## 3. DLE Return Envelope Format (Required Response Format)

To integrate seamlessly back into the DLE, the review output must conclude with a structured JSON block matching `evaluation_type: "peer-review-feedback"`:

```json
{
  "schema_version": 1,
  "evaluation_type": "peer-review-feedback",
  "review_timestamp": "ISO-8601-TIMESTAMP",
  "reviewer_identity": "ChatGPT-Peer-Reviewer",
  "scores": {
    "architecture_viability": 1-10,
    "hardware_allocation_efficiency": 1-10,
    "sovereignty_and_dle_compliance": 1-10,
    "harness_and_routing_resilience": 1-10
  },
  "critical_findings": [
    {
      "area": "string",
      "severity": "low|medium|high|critical",
      "observation": "string",
      "recommendation": "string"
    }
  ],
  "tactical_improvements": [
    "string"
  ],
  "overall_verdict": "string"
}
```
