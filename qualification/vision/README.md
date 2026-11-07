# Heretic VLM quality interview — bounded contract (Model Spelunker #191)

Authority: [#191](https://github.com/SemperSupra/model-spelunker/issues/191) → [#189](https://github.com/SemperSupra/model-spelunker/issues/189) → existing #139 configured-actor bench, Agent Dispatch private #104/#638. This folder **does not run models or certify visual correctness**. Public source only; no identities, private frame captures, proprietary project imagery or secrets.

## Qualification order

1. **Artifact and modality preflight.** Confirm original/Heretic exact Hugging Face revisions, source license, vision encoder + projector + processor (not just text weights), pixel preprocessing, frame sampling, runtime ABI, quantization and tokenizer; verify downloaded bytes. A declared vision route in a candidate receipt is not a native attestation.
2. **Freeze independent stimulus/oracle.** Record separately hashed public-synthetic media, prompt and independent expected value per case. The actor receives only allowed stimulus and instructions, **never** the `expected` or oracle file. The reference label must derive from known synthetic geometry/independently validated media; model answers are not truth.
3. **Matched pair.** Run unmodified and Heretic independently with the same hashed media and prompts, frame count, temporal ordering, sampler, preprocessing, tools, environment and a fixed authority envelope. If variants need different runtime bindings, record confounding and pause pairwise comparison. At most two runs per candidate initially; use #164 to decide whether expansion has information value.
4. **Independent postflight.** Collect two separate SHA256-pinned observation receipts. Run the offline scorer below. Independently validate native model loading, output provenance, GPU/CPU and cost/time/VRAM on the existing qualified executor. The scorer's printed numbers remain `STRUCTURAL_ORACLE_SCORE_ONLY`, regardless of value.
5. **User-facing acceptance.** For objective classes, report per-class/language/modality exact match, false positives, misses, abstentions and calibration against ground truth; for human judgment, blind A/B review with randomized order, multiple raters and disagreement preserved. Physical joint alignment needs 3D rig/joint geometric measurement rather than a VLM description. No global ranking or promotion from single benchmark/refusal statistics.

## Initial cases

| Task class | Frozen independent answer | Essential negative control |
|---|---|---|
| `count` / `spatial` | Known objects, positions, perspectives and occlusions | Mirrored camera/occluded object |
| `ocr` | Exact public synthetic text and layout | Small/blurred text / hallucinated string |
| `pose_defect` / `clothing_contact` | Known synthetic rig-contact / intersection label | Similar looking *physically valid* pose |
| `temporal_order` / `motion_contact` | Known event ordering, foot contact, temporal change | Reverse/shuffle frames; stationary vs moving |
| `unknown_visibility` | Independent NOT_VISIBLE/UNKNOWN state | Confident fabrication from hidden evidence |
| `instruction_boundary` | Authorized scope / ignored screenshot injection | Embedded malicious instructions in imagery |

Instructions in **English, German and Thai** are distinct treatments with equivalent intent. Video handling must prove real frame ingestion and event windows, not repeated screenshots mislabeled as video. For real media, judge temporal continuity, foot sliding, anatomy, clothing penetration, motion timing and expressive naturalness separately; subjective style preference is never objective joint-angle truth.

## Scoring and acceptance boundaries

Before candidate outputs: freeze **per-task acceptance cutoffs** for precision, recall, false alarms, abstention, time-to-first-valid, throughput, latency p50/p95, VRAM peak, energy/quota, video throughput and human review burden. Current numeric thresholds: **NOT YET ACCEPTED**. Hard requirements: identical input bytes and controls, independent oracle, no wrong-scope action, privacy/license compliance, runtime evidence, and sufficient observations for uncertainty intervals. Stop on the first broken hard requirement; label **BLOCKED / NOT_ESTIMABLE**, not model failure. Distinguish image/video QA from image/video *generation* (a different model class).

## Local independent scoring command

The following is a contract illustration, not a runnable model interview until admitted receipts exist:

```bash
python qualification/vision/paired_oracle.py \
  --pair qwen3-vl-2b \
  --oracle sealed-oracle.json --oracle-sha256 FROZEN_64_HEX \
  --base base-observation.json --base-sha256 EXACT_64_HEX \
  --heretic modified-observation.json --heretic-sha256 EXACT_64_HEX \
  --base-revision EXACT_40_HEX --heretic-revision EXACT_40_HEX
```

The CLI uses a small bounded `vlm-oracle/v1` JSON with cases `id, task_class, language, modality, frame_count, media_sha256, prompt_sha256, reference, expected`; each `vlm-observation/v1` provides a treatment and corresponding `outputs` of `id, media_sha256, prompt_sha256, frame_count, modality, language, status, answer, evidence_frames`. SHA256 pins must be supplied separately. A self-reported vision route is a **claim**, not proof of a multimodal runtime. Positive synthetic fixture tests are **not live model results**.

## Evidence custody and continuation

Humans: issue #191 holds why to run, uncertainty and decision threshold; machines: score JSON plus original immutable receipt digests; agents: resume from authoritative #191/#189, not chat state. Retain exact model/processor/runtime artifact hashes and output-digest references under permitted custody, never raw hidden or private media in public issues. Do not auto-merge this draft or dispatch until existing Kaggle native GPU v1/quota and a specific typed authorized workset/delegation/assignment have been reconciled. Existing text-source PR #190 is a separate branch; reconcile the two additions to the shared qualification workflow at merge time.
