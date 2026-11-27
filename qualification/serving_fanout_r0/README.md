# Serving fan-out R0 — public-safe synthetic experiment

Authority: [Model Spelunker #316](https://github.com/SemperSupra/model-spelunker/issues/316). Parent #306. Configured-actor interview owner #139.

This is an offline **abstract discrete-event simulation** of admission contention, not a production scheduler, model server, GPU benchmark, or proof of live reliability. It must never be used as a measured BigMac/TrueNAS performance result.

Reproduction from `protocol/`:

```sh
go test -count=3 ./...
go run . -fixture ../workloads/illustrative-2slot.json -policy fifo
go run . -fixture ../workloads/illustrative-2slot.json -policy reserved
```

Fixture: two batch requests arrive at t=0, each needing 50 abstract service ticks; two interactive requests arrive at t=1 and t=2, each needing one tick. Under simple FIFO, both slots fill with batch work, which delays interactive jobs. A reserved policy protects one interactive slot, but decreases batch throughput. This is an illustrative trade-off only: real backends have preemption limitations, variable service rates, model load costs, KV memory, prefix reuse, cancellation, multiuser trust boundaries, GPU pressure, and cache invalidation that the simulator *does not model*.

Receipt field `evidence_class` is always `SYNTHETIC_SIMULATION_NOT_HARDWARE`, with a canonical fixture SHA-256 and per-job observations. Negative controls reject malformed classes, duplicate tasks, and invalid reservations. Future G1/G3 requires independent red-team tests, real harness task-validator success and separately authorized HIL; no production backend writes or private CI spends.

The relevant research is a methodological starting point, not a validated product selection: MLPerf multi-turn agentic evaluation, llama.cpp server slots and KV controls, and vllm-metal concurrency studies. All exact binary/version identities must be pinned for real measurements.
