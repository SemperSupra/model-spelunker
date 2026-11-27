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

## R14 — Non-promoting live G2 evidence eligibility screen

The optional **offline** `go run . -live-gate fixtures/live-r7-public-cpu.json` projects source-labeled live public experimental summaries into a fail-closed reviewer status without touching runtime queues or changing original R1 synthetic reducer behavior. This is deliberately a small extension of the existing independent analysis workcell, **not a new scheduling/admission service**. A complete source-labeled tuple includes a 40-character source commit, 64-character artifact ZIP digest, model runtime representation digest, attempted/independently validated task counts, task-class coverage, number of independent public/sovereign host runs, per-condition replications, streaming TTFT, physical memory observations, model admission, tenant binding, backend bypass closure and observed admission invariant violations.

Predeclared decisions: any recorded admission violation => `REJECT_ADMISSION_INVARIANT`; any failed independently attempted task => `REJECT_TASK_QUALITY`; no admitted sovereign host, fewer than two verified task classes, fewer than 3 independent hosts/10 trials per condition, absent proper resource/identity readings => `INSUFFICIENT_EVIDENCE`; all dimensions supplied => `ELIGIBLE_FOR_INDEPENDENT_REVIEW_ONLY`. **`automatic_promotion` is always `NEVER`**. It cannot independently authenticate source bytes, artifact download or authority: output declares `origin_authentication=NOT_PERFORMED_ON_SUMMARY_METADATA`. Supplying fake true booleans cannot confer release authority; subsequent primary artifact checking and owner-signed gates are required.

Fixture `live-r7-public-cpu.json` is **a manually source-labeled projection**, not a signed/reduced primary artifact. It references the actual R7 public 24-task cohort from [PR #337](https://github.com/SemperSupra/model-spelunker/pull/337) and [run 45173592480](https://github.com/SemperSupra/model-spelunker/actions/runs/45173592480), artifact SHA256 `0904c7f87f6e6b2abd2f3124eee2e579d08426a6bbe0b768d0a9532b6a74110e`. Even **24/24** independently validated tasks in this one small class on one public CPU runner are deliberately **INELIGIBLE** for sovereign production qualification. Tests also exercise R9 task verifier negatives, R10 native queue counterexample, and R13 mTLS quota positives without tenant mapping, plus malformed source labels and unauthenticated self-promotion claims.
