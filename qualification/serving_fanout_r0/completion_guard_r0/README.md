# OpenWorker required-output completion guard R0

Owning authorities: [configured actors #139](https://github.com/SemperSupra/model-spelunker/issues/139) and [inference/goodput #316](https://github.com/SemperSupra/model-spelunker/issues/316).

This is a bounded public CPU experiment on the existing canonical runner and
admitted OpenWorker artifact. It measures an opt-in change to the existing
TurnEngine loop. It adds no agent runner, task verifier, inference gateway,
scheduler, or deployment. Native model outcomes are not pre-judged.

## Why this treatment

Frozen ISH [#433](https://github.com/SemperSupra/model-spelunker/pull/433), run
[46086572682](https://github.com/SemperSupra/model-spelunker/actions/runs/46086572682),
accepted all nine text-repair attempts and zero of nine validation-discovery
attempts. All discovery attempts listed files once, then stopped after two
model calls without reading a file or creating the required output. All native
recovery boundaries completed. Making these failed attempts faster did not
produce accepted work. The original attempt receipts and task oracles remain
unchanged.

The testable hypothesis is that one bounded notification of absent, explicitly
required output files can recover a premature stop within the original total
four-call budget. It cannot detect incorrect contents in an existing file,
discover the right answer, override permissions, or increase the call budget.
The existing independent canonical verifier remains the sole task-acceptance
authority. No verifier contents, expected answer, or private fixture are sent to
the model.

## Frozen design

Three public standard Ubuntu jobs each execute four serial attempts: two
unchanged task packages times two completion modes. There are **12 attempts**,
with three paired blocks per task. Each arm starts a fresh native server to
isolate cache state, then keeps it resident for the whole task. There is no
restart/recovery factor.

| Factor | Value |
| --- | --- |
| Task packages | `text-repair-v0`, `validation-discovery-v0` |
| Required outputs, explicitly declared | `value.txt`, `result.json`, respectively |
| Control | `MODEL_SPELUNKER_COMPLETION_CHECK=none` |
| Treatment | `MODEL_SPELUNKER_COMPLETION_CHECK=required-files-v1` |
| Model-call budget / output limit | Four calls / 256 tokens per call in both arms |
| Native sampling | Seed 42, temperature 0, thinking disabled |
| Native server | One slot, context 8192, four CPU threads, zero GPU layers |
| Lifetime | New process per arm, resident during task, explicit teardown |
| Order | Paired order alternates by block and task; each mode starts three of six pairs |
| Promotion | None; synthetic framework feasibility evidence only |

The candidate documents differ only in completion mode. Both bind the same
explicit output list, task package digest, source-file hashes, tool projection,
iteration/token limits, sampling extras and server flags. The disabled guard
does not inspect files; its observed requirements list is empty. Required-output
presence is feedback, not semantic acceptance.

The same exact pins as #433 are retained: OpenWorker source
`5bc10d928e0b64aae74313349a3b17bd19643ae2`, admitted OCI digest
`sha256:e8c9da992ee4c1ce3934e6e9874c3129c4b00cec38428ed9cf1fe47190a9fe83`,
llama.cpp `a6ac41c757c066941766164439f6876f2deaab04`, and Qwen3 1.7B weight
`sha256:3d0b790534fe4b79525fc3692950408dca41171676ed7e21db57af5c65ef6ab6`.
The Ollama manifest, release archive, harness payload and native executable
identity are checked or recorded. Ollama only hydrates the public GGUF; native
llama.cpp performs inference.

The pinned provider forwards `extra_body` through the OpenAI SDK; an installed
provider preflight proves this without network/model use. The adapter talks
directly to the loopback native server. There is no measurement relay.

## Evidence and gates

Every arm retains packet, candidate, full v2 experiment declaration, canonical
receipt, allowed-output snapshot, sanitized diagnostic projection and result.
The fixture checks exact source/task/configuration/experiment/launch joins,
rechecks output bytes against the snapshot manifest, and runs the unchanged
canonical verifier against that snapshot. A correct output with a failed or
timed-out actor does not become an accepted attempt.

The canonical diagnostic tail supplies the final `completion_guard` summary.
The nudge marker exists only when a nudge occurs; the disabled control therefore
does not require one. When present, its mode, requirements digest and count
must agree with the final summary. Diagnostic output includes only allowlisted
metadata, counts and hashes; raw model text, tool arguments, approval paths,
native logs and raw diagnostics are not uploaded.

Native input/cache/output counts are observed through the pinned provider's
usage parser and canonical receipt. Missing telemetry stays UNKNOWN. This
experiment does not claim raw SSE terminal verification or detailed native
prefill/decode timing. Accepted attempts, false completions, errors and
timeouts remain distinct.

Every generated experiment declaration and receipt is checked against the
existing canonical schemas. This matters because frozen #433 used the
unsupported `framework-proving` claim type, an integer design block, and an
extra model `source_manifest` field. Its runner also emitted finish-reason
counts absent from the old schema. R0 uses schema-valid `feasibility`, string
blocks, complete v2 declarations, model manifest in configuration, and the
additive schema field for already-emitted canonical finish counts. It does not
rewrite historical evidence.

The workflow gates on valid infrastructure/evidence and stopped native
processes, **not task success or an improvement threshold**. Zero benefit is a
valid result. Report each task separately, keep every attempt's cost, and check
whether the text-repair control regresses before interpreting discovery gains.

`total_wall_s` includes native startup, the task, independent verification,
diagnostic projection and teardown. Build/hydration cost lies outside that
interval. Summed lifecycle times are not campaign makespan; repeated accepted
synthetic attempts are not unique production deliverables. Public CPU evidence
does not qualify BigMac, TrueNAS, other harnesses or larger models.

## Local checks and prospective execution

```sh
python -m unittest qualification.test_completion_guard qualification.test_run_receipt_finish_counts
python qualification/serving_fanout_r0/completion_guard_r0/prove.py --self-test
# After installing the exact admitted harness:
python qualification/tests/test_completion_guard_native.py --require-native
python qualification/serving_fanout_r0/completion_guard_r0/prove.py --provider-self-test
```

The new workflow `.github/workflows/openworker-completion-guard-r0.yml` runs
those gates before model hydration/build. It launches three public standard
CPU jobs, caps each at 45 minutes, and keeps only compact evidence artifacts
for 14 days. It does not access physical hosts, private task content, paid
inference or private Actions runners.
