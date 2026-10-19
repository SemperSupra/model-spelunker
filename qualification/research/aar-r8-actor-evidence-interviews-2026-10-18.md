# AAR Kotlin/R8 evidence-interpretation actor qualification — 2026-10-18

Source-known upstream owner: `SemperSupra/android-artifact-recovery` [draft PR #39](https://github.com/SemperSupra/android-artifact-recovery/pull/39), R8 matrix [GHA #39100419641](https://github.com/SemperSupra/android-artifact-recovery/actions/runs/39100419641), JVM/repair evidence [GHA #39101587693](https://github.com/SemperSupra/android-artifact-recovery/actions/runs/39101587693). The two **separate task/evaluator contracts** live in this Model Spelunker PR #186 (existing actor qualification issue #139). They are not an implementation of a decompiler, not a private APK campaign, and not a Kotlin/ART behavior oracle.

## Task admission vs actual actor performance

Existing [Qualification Contract Check #39116211253](https://github.com/SemperSupra/model-spelunker/actions/runs/39116211253), [Portability Rehearsal #39116211282](https://github.com/SemperSupra/model-spelunker/actions/runs/39116211282), and [Harness Artifact Portability #39116211233](https://github.com/SemperSupra/model-spelunker/actions/runs/39116211233) all succeeded. Both `verify.py --self-test` tests cover positive and adversarial controls; strict citations/UNKNOWN constraints are enforced. **This is verifier correctness on source-known fixtures**, not actor admission.

Configured-actor baseline: already admitted OpenWorker OCI `ghcr.io/sempersupra/model-spelunker-harness-openworker@sha256:e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83`, local GHA Ollama 0.34.1, pinned `qwen3:1.7b` SHA256 `8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7`, three projected tools `list_files, read_file, write_file`, maximum 4 tool iterations and 120-second task limit, public ephemeral Ubuntu 24.04 runner. No external inference, paid provider, private source or device action.

| Treatment | Evidence task | Authoritative run | Model completed task? | Model/tool observation |
| --- | --- | --- | --- | --- |
| No extra hint | `aar-r8-factor-contrast-v0` | [#39116351656](https://github.com/SemperSupra/model-spelunker/actions/runs/39116351656) | **FAIL** / verifier 1 | 1 read_file, 0 write_file; false completion |
| No extra hint | `aar-r8-jadx-repair-triage-v0` | same | **FAIL** / verifier 1 | 1 read_file, 3 write_file, but no successful final state; false completion |
| `inspect-before-claim-v1` | `aar-r8-factor-contrast-v0` | [#39116590794](https://github.com/SemperSupra/model-spelunker/actions/runs/39116590794) | **FAIL** / verifier 1 | 1 list_files, 0 read_file, 0 write_file; false completion |
| `inspect-before-claim-v1` | `aar-r8-jadx-repair-triage-v0` | same | **FAIL** / verifier 1 | 1 list_files, 0 read_file, 0 write_file; false completion |

**Important distinction:** GitHub Actions workflow jobs all concluded **SUCCESS** because the workflow verifies that the *failed actor observation was correctly recorded*. All four task verifiers returned exit 1 / `observation.success=false`. Do not present green GHA as model qualification. A hint cannot be called helpful or harmful from this single unrepeated pair. User-authorized real inference was local within public free-tier GHA; it made no API charges.

Current outcome: **ZERO of four actor/task treatments admitted**, evaluator/fixture/transport substrate operational. No semantic equivalence or original-name recovery demonstrated. Both tasks test classifying actual R8/JADX evidence, not decompiling a real APK method.

## Corrective actions, preserving existing authority

1. Do not expand the task grader to accept missing writes or invented citations; retain negatives. Before another run, inspect OpenWorker's tool-call trace under its existing authorized diagnostic mechanism (do not upload raw prompts or private data) to distinguish context overrun, tool-projection mismatch, abort vs premature finish, and low-model capability.
2. Qualify a second exact model and/or stronger task-compatible actor with **existing** Model Spelunker configured-actor runner, not a duplicate benchmark. Contrast `none` and `inspect-before-claim-v1` as separate treatments only with repeated randomized execution. Preserve model digest, harness OCI digest, temperature, reasoning, task SHA, source evidence references, tool projection, receipt and wall time.
3. Upgrade to a real *method-level* Kotlin/JVM/DEX source-known witness, beginning with the AAR GoldenRecordFingerprint Kotlin 2.0.21 class and two distinct source-known visibility/overload signatures derived from actual R8 output. Build them with source/mapping restricted to evaluator, compare native DEX access flags/JADX output, and independently test behavior; treat missing pieces UNKNOWN.
4. Reuse AAR PR #42's actual EvidencePrompt/AssistGateway for interactive JADX assistance, but do not conflate the GUl plugin's controlled JSON completion with OpenWorker's multi-tool write-file harness. Prompt, toolset and model route are independent factors.
5. If/when external OpenRouter free or BYOK actors are admitted, use already governed controller child-credential lifecycle; do not transfer private APK code, mint management keys in public cloud, or conflate provider cost/credit routes.

**Resource economics:** A one-shot PR-triggered GitHub Actions wrapper produced the four real model receipts. Remove that wrapper from this PR after observing these outcomes. Subsequent runs should explicitly use existing `workflow_dispatch` Model Spelunker qualification capabilities and an authorized actuator; do not auto-pull Qwen weights on every documentation edit. PR #186 remains DRAFT/unmerged. AAR-private #82 remains portfolio-specific DLE authority.
