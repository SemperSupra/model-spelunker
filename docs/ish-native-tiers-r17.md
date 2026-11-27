# ISH R17 — Native cache tiers and sleep/wake

Public synthetic R&D evidence, not a deployment profile. Authority [#316](https://github.com/SemperSupra/model-spelunker/issues/316). Exact native CPU fixture: llama.cpp `a6ac41c757c066941766164439f6876f2deaab04`, Qwen2.5-0.5B-Instruct Q4_K_M model digest `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db`, model revision `6dd44a1fb35d11b5d1b28902876ce3cc9e882d0e`. Three repetitions, rotated five-arm order, independently correct retrieval and exact token sequences across arms.

[Run 46040224740](https://github.com/SemperSupra/model-spelunker/actions/runs/46040224740), source head `725f04d0cab8456baaebe9946011761db2cb6127`, tested merge SHA `874d11455585cb2b0dd7db073ebef05d8805d75c`, artifact 15219194788 SHA256 `9e3905c3f31e533d1224746e49b74baf8623539c88693674c09fbab0dc5cddfa`, independently rehashed. Workflow merged via #413 without changes to executable source.

| Treatment | Evaluated prompt tokens per rep | Mean continuation wall (s) | Interpretation |
|---|---|---:|---|
| RAM disabled | 923,925,923 | 5.413586 | Some shared resident prefix, not fully cold |
| RAM 1MiB | 948,948,948 | 5.538695 | Native oversize refusal observed |
| RAM 64MiB | 29,29,29 | 0.412108 | Native idle save and RAM restore observed |
| Native sleep only | 948,948,948 | 5.874488 | Actual sleep/wake; original RAM state lost |
| Native sleep + disk | 29,29,29 | 0.401792 | Native snapshot restores state after reload |

Wake-through-result mean with disk 0.795002s, including wake/restore and continuation; pre-sleep durable publication mean 0.017614s; native-only wake-through-result 5.874488s. Process RSS during sleep ~79.1 MiB versus awake ~700.5 MiB (not cgroup/GPU/system memory). Do not conflate disk-arm continuation-only wall with complete wake wall.

## Metal and simulator

[Metal run 46039854261](https://github.com/SemperSupra/model-spelunker/actions/runs/46039854261) native upstream host and disk-after-restart oracle: 992 restored, 11 recomputed, EXACT output in both, disk read counter 113770496 bytes. Artifact 15219019365 SHA256 `67e88087a65ac064e3ee12a60e1b34e3af0b7c41963373e8a99a1cdcd9015883`. Upstream vLLM-Metal v0.34.0, pinned Qwen3-0.6B MLX representation; native CPU/MPS/MLX dependency treatment to be tested separately. Declared vLLM Torch 2.14.0 was overridden by upstream Torch 2.16.0.dev20261013; metadata exception remains until qualified. Metal docs warn disk keys do not bind exact weight bytes: production store must be isolated by exact identity before use.

[SGLang run 46039609103](https://github.com/SemperSupra/model-spelunker/actions/runs/46039609103) failed before cache qualification. Artifact 15220600449 SHA256 `8192554ad225d1d93b8a4fdf8e9f9cf80aeeab8e657ba032cbc1c1725c576662`. AIC 0.10.0 pins NumPy1.26.4; ml-dtypes0.7.0 requires NumPy2, causing ABI import failure. Corrective experiment pins ml-dtypes0.5.3 (source declares Python3.12 NumPy>=1.26) and resolves in one install, validates metadata/imports before unchanged upstream tests. No claim of simulator PASS until terminal receipt.

## Limits

The two native mechanisms are real, but are not a matched engine/quantization or physical target performance comparison. No production tenant isolation, task-goodput, GPU cache residency or power-loss durability acceptance follows from these fixtures. Use exact runtime/model/cache layout and authorized session identity. Keep durable logical work independent of transient inference state. No runtime deployment is implied.
