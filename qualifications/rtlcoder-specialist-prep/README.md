# RTLCoder specialist preparation

This lane is preparation only. It must not start a model download or inference job until the OpenWorker portability experiment is interpreted.

## Candidate

- model: `ishorn5/RTLCoder-v1.1-gguf-4bit`
- exact Hugging Face revision: `fc60b2440a782487654f573bbaed2c8a39647e8e`
- artifact: `ggml-model-q4_0.gguf`
- exact artifact SHA-256: `860753548c58bc298db10e0173e73b73f89724ce848b6be1491cd01eb7131a54`
- size: `4108921984` bytes
- observed license: Apache-2.0
- role: bounded Verilog-generation specialist, never the authority-bearing controller

The official RTL-Coder project identifies this GGUF as the CPU-capable 4-bit version of RTLCoder-v1.1.

## Planned experiment

Hold the selected controller persona realization fixed after the framework-portability decision. Add one capability only:

`generate_verilog(spec) -> candidate RTL text`

The controller remains responsible for deciding when to invoke the specialist, writing the candidate through the existing bounded write tool, running the independent `iverilog` oracle, interpreting failures, and repairing or rejecting the result.

The first comparison reuses `rtl-popcount4-v1`; no new benchmark suite is required for the initial specialist-amplification question.

## Gate

Do not execute until:

1. the OpenWorker portability run is complete and interpreted;
2. one framework realization is selected for the specialist comparison;
3. the specialist bytes are verified against the pinned SHA-256 before inference.

A failed scientific result is retained and is not automatically retried. More RTL fixtures or repetitions are added only if the first specialist result creates an ambiguity worth resolving.

## Resource-bounded execution shape

When the framework gate is satisfied, use one adaptive public-runner job rather than two separate model jobs:

1. download the exact pinned RTLCoder GGUF and verify SHA-256;
2. import it from the verified local file into the pinned Ollama runtime;
3. run one standalone `rtl-popcount4-v1` specialist smoke test through the independent iverilog oracle;
4. if the specialist fails, preserve the negative result and stop before downloading the controller;
5. only if the specialist passes, pull the already-qualified Qwen3.5 controller and run the complete specialist-augmented persona on the same runner;
6. keep `OLLAMA_MAX_LOADED_MODELS=1` so the two ~4B models do not need to remain resident together.

The integrated persona should expose the specialist only as `generate_verilog(spec) -> candidate RTL text`. The controller remains responsible for writing, testing, repair, and the final decision. This preserves the authority boundary and avoids a speculative model/framework matrix.
