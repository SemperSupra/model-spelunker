# Cross-model conditioning DOE — source-only contract

Authority: Model Spelunker #193 → #191 / #189 → existing #139 harness, Agent Dispatch private #104/#638 admission. This is not an inference runtime, model registry, or scheduler.

## Adopt-before-build candidates

1. Z-Image-Turbo (Tongyi-MAI/Z-Image-Turbo; Apache 2.0) uses Qwen3-family encoding. Compare the stock generator-native encoder from Comfy-Org/Z-Image-Turbo to community CCSSNE/DreamFast-qwen3-4b-heretic, holding the generator, VAE, prompt, seed, sampling and environment fixed.
2. FLUX.2 Klein 4B (black-forest-labs/FLUX.2-klein-4B; Apache 2.0). Comfy-Org repack lists qwen_3_4b.safetensors and flux2-vae.safetensors. Publisher also claims compatibility with the same Heretic encoder. Compare against the native stock file from Comfy-Org/Flux-2-Klein-4B. The public source census proves that this stock Comfy encoder and Z-Image's stock Comfy encoder are the **same publisher-reported file OID**, saving one redundant baseline download. ComfyUI's Z-Image text path uses hidden layer -2, while Klein uses [9, 18, 27] and a different prompt template. Do not substitute one generator's tensor outputs for the other.
3. Krea 2 with Qwen3-VL-4B is NOT interchangeable with Qwen3-4B. It taps twelve intermediate hidden-state layers and passes them to a model-specific adapter. Evaluate as a separate future treatment.
4. Reasoning-based prompt rewrite and independent VLM critique are additional later factors, not evidence of a hidden-state encoder improvement.

Sources:
- https://huggingface.co/Tongyi-MAI/Z-Image-Turbo
- https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
- https://huggingface.co/Comfy-Org/Flux-2-Klein-4B
- https://huggingface.co/Comfy-Org/Z-Image-Turbo
- https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/text_encoders/z_image.py
- https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/text_encoders/flux.py
- https://huggingface.co/CCSSNE/DreamFast-qwen3-4b-heretic
- https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/text_encoders/krea2.py

Native source evidence: qualification/conditioning/source-observations/conditioning-hf-20261112.json — six source repositories, 33 published Safetensors OIDs/sizes, exact repository commits, public GHA run 43190428793/job 131088046310; neither weights nor image outputs were downloaded or hashed. Stock Comfy encoder SHA256 published by BOTH repacks: 6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a. This is publisher-reported source identity, not local byte attestation. The bare Qwen/Qwen3-4B upstream shards do not share every published file OID with generator-packaged text-encoder shards, so never claim their underlying tensors are identical without verification.

These are publisher/source claims, not independently completed local inference.

## Three independently executable workcells

**A. Public source / CPU CI:** Pin exact original/Heretic and generator+VAE weights by exact repo revision and checked downloaded file-byte digest; determine tokenizer/processor, loader, adapter, license and ComfyUI commit. Validate the bounded, synthetic-data conditioning-doe-plan/v1 JSON with paired_protocol.py. No weights, network dependency or GPU on CI. Maximum two seeds, six prompts, and two arms = 24 planned images per generator. Fixture hashes in unit tests are intentionally synthetic and never count as model evidence.

**B. Approved local HIL:** Use a disposable, pinned ComfyUI container with one admitted TrueNAS RTX A5000; separately precheck service GPU contention, free VRAM and host/container policies. Read-only model mount, disposable output/cache, LAN-only endpoint, no host taint. Observe native container digest, CUDA/driver/PyTorch, model/processor hashes, frames, prompt, seed, output bytes, wall time and VRAM. Do not take both GPUs or stop Ollama without separate admission. If no qualified venue or assignment exists, leave runtime HOLD. The historical Kaggle GPU version-1 must be observed before any new Kaggle workload.

**C. Independent quality:** Freeze public synthetic scenes/prompts and known labels before generation, compare original vs Heretic blind within each generator, evaluate composition/count/text/spatial fidelity and human character/garment quality separately. VLM self-ratings cannot be ground truth. Track first-pass successes, false positives, subjective disagreements, time, peak VRAM and operator attention. Thresholds must be preregistered and owner-accepted before seeing outputs; stop after first informative negative control and use the #164 information-gain reducer.

## CLI handoff (Python 3.12, ephemeral runner)

Plan only (no actual inference):
    python qualification/conditioning/paired_protocol.py --plan approved-z-image-plan.json --plan-sha256 EXACT_64_HEX

Check external proposed run receipt structure (not native runtime attestation):
    python qualification/conditioning/paired_protocol.py --plan approved-z-image-plan.json --plan-sha256 EXACT_64_HEX --observations approved-observations.json --observations-sha256 EXACT_64_HEX

Plan packet must pin generator, VAE, workflow, runtime image, ComfyUI commit, preprocessing, dataset, prompts, seeds, two encoders and same quantization. Structural observations must account for every original and Heretic pairing and preserve input/controls hashes. Source-only result can be PLANNED_ONLY or STRUCTURE_ONLY, never an actual inference or quality PASS. Native provider logs and downloaded image/weight bytes are independent evidence.

## Durable outcomes

Human: paired image quality, confounders and uncertainty. Automation: immutable plan/control digests and native result references. Agents: resume #193 / source PR rather than chat state. No private project people/media/credentials in public CI or GitHub comments. Existing independent draft PRs #190 and #192 also modify the shared qualification workflow; integrate their steps additively, never force-merge.

State: CONTRACT_STAGED / MODEL_FILE_HASHES_NOT_ATTESTED / LOCAL_GPU_NOT_ATTESTED / GENERATION_NOT_EXECUTED / IMAGE_QUALITY_UNKNOWN.
