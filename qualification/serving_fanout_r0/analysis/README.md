# Independent synthetic evidence reducer — R1

Authority: [Model Spelunker #316](https://github.com/SemperSupra/model-spelunker/issues/316), parallel to draft PR #317 and fault oracle #318.

This Go standard-library tool **does not simulate, route, run a model, or make deployment decisions**. It verifies pairwise synthetic receipt structure, timeline ordering, aggregate statistics and task-set equality, rejecting many forms of false result promotion.

```sh
cd qualification/serving_fanout_r0/analysis
go test -count=3 ./...
go run . -baseline fixtures/fifo.json -candidate fixtures/reserved.json
```

The fixtures represent exactly the original two-slot illustrative experiment. The fixed 64-hex fixture digest is calculated from the canonical Go JSON representation of `qualification/serving_fanout_r0/workloads/illustrative-2slot.json` in PR #317, not a cryptographic signature. Equal digest strings are **not** proof of originating from trusted source, and this reducer does not independently verify the original weight/model/harness/host identity.

The output always declares `SYNTHETIC_RECEIPT_REDUCTION_ONLY`, statistical uncertainty not estimable from one synthetic fixture, and `NO_RUNTIME_PROMOTION`.

Future releases must add authenticated artifact provenance, independently seeded replicated tasks, resource/quality validation and appropriately calibrated uncertainty before issuing any promotion advice. Failing input is never silently omitted; compare does not infer backend adherence to reserved-slot policy from timestamps alone.
