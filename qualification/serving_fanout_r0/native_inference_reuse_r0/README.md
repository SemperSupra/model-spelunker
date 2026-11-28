# Native CPU fixed inference reuse R0

This experiment asks whether one exact native llama.cpp artifact can complete
the same fixed task on its producer and a fresh consumer. It extends the
accepted [native build reuse proof](../native_build_reuse_r0/) by composing its
producer, archive verifier, dependency checks and fault controls unchanged.
The existing archive manifest remains explicitly scoped to CLI qualification;
the separate `case.json` and `pair.json` are the additional inference evidence.

## Fixed case

| Input | Exact selection |
|---|---|
| Substrate | Standard public GitHub Actions `ubuntu-24.04`, x86_64 CPU |
| Native source | llama.cpp `a6ac41c757c066941766164439f6876f2deaab04` |
| Build | Release, `GGML_NATIVE=OFF`, server only, two build jobs |
| Model | `qwen3:1.7b`, one GGUF of 1,359,279,776 bytes |
| Manifest | `sha256:8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7` |
| GGUF | `sha256:3d0b790534fe4b79525fc3692950408dca41171676ed7e21db57af5c65ef6ab6` |
| Harness | Existing admitted OpenWorker `5bc10d928e0b64aae74313349a3b17bd19643ae2` artifact |
| Task | Unchanged `text-repair-v0` and external `verify.py` |
| Serving | Context 8192, one slot, four CPU threads, zero GPU layers, Jinja, no idle-slot cache or cache RAM |
| Requests | Seed 42, temperature 0, slot 0, prompt cache enabled, thinking disabled |
| Actor | Four model calls, 256 output tokens, nonparallel tools, no tool hint, repeat policy disabled |
| Time budget | Explicit **240-second cloud task override**, 300-second outer runner envelope |

The task package itself still declares 120 seconds. This experiment's cloud
override is recorded in its candidate and launch evidence; it is not a change
to that task package or an implicit budget for another environment. The native
server has a 60-second readiness limit, a 10-second graceful teardown limit,
and the independent snapshot verifier has a 15-second limit.

## Execution and acceptance

The producer builds once, hydrates the pinned public model and harness, stops
the hydration-only Ollama process, and runs the packaged binary through the
canonical runner and real projected adapter. An immutable same-run Actions
artifact contains the exact native tar and the producer case. The consumer
checks that exact artifact ID/digest, current run/attempt/source identity,
complete native file inventory and external dependencies before independently
hydrating the same inputs and running its case. No consumer build occurs.

Both cases must pass the unchanged external oracle, preserve a complete output
snapshot, and have a schema-valid receipt joined to the task, source, candidate,
launch packet, experiment and substrate. A correct file with a nonzero child,
timeout, engine error or incomplete teardown does not qualify. Native `/props`
must confirm the declared context, slot count, model alias and model path.
The reported default and tool-use template digests are joined across runners.
No oracle implementation or hidden expected answer is added to the actor's
task workspace.

Seven focused test methods corrupt model identity, output/snapshot integrity,
receipt bindings, engine outcomes, settings, deadlines and teardown. Existing
native artifact tests and fault controls remain separate. A failed attempt is
retained and stops the cell; model tasks are not automatically retried.

## Reading the evidence

Build, transfer/admission, harness/model hydration, native readiness, canonical
task execution, independent verification and teardown have separate timing
fields. Job intervals start on the assigned runner and exclude provisioning,
queue wait and final evidence upload. Canonical runner time includes its own
verification; the separately reported snapshot check is a second verification.

One accepted producer/consumer pair demonstrates compatibility for this exact
case. It does not estimate a general success rate, tail latency, causal speedup,
GPU compatibility, another platform's performance or OS containment. Identical
inputs and output-oracle acceptance do not require identical generated text on
different CPUs. Fresh processes and model hydration are included and visible;
the task window starts after native readiness. No physical-host authority is
created by this public experiment.
