# R1 falsification lane — modeled reliability only

DLE: [Model Spelunker #316](https://github.com/SemperSupra/model-spelunker/issues/316). No production queue, backend scheduling, authorization, physical KV or network interactions.

Run offline:
```sh
cd qualification/serving_fanout_r0/falsification
go test -count=3 ./...
go run .
```

This *finite-state model* exhaustively explores reachable states up to nine transitions, with explicit assumptions. It distinguishes (a) an acknowledged job whose durable record survives process crash, (b) a generation-fenced lease, (c) admission and execution authorization/qualification, and (d) an idempotent side-effect destination. Its RED negative control removes downstream deduplication, producing a counterexample with crash/replay and duplicate side effect.

No finite-state proof of this abstraction establishes live reliability, physical persistence, exactly-once side effects, tenant isolation of KV caches, or correct runtime credentials. Those are separate G2/G3/G4 empirical/integration gates and must be evidenced independently. Model does not represent distributed partitions, durable-store corruption, multi-job resource exhaustion, or Byzantine actors.

Public output is labeled `SYNTHETIC_FINITE_STATE_NOT_PRODUCTION`. Preserve negative counterexamples when revising the contract.
