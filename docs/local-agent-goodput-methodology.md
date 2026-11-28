# Local agent goodput: cloud methodology and transfer plan

Review date: 2026-11-28. Authorities: [configured actors #139](https://github.com/SemperSupra/model-spelunker/issues/139), [harness/engine/memory #306](https://github.com/SemperSupra/model-spelunker/issues/306), [serving/goodput #316](https://github.com/SemperSupra/model-spelunker/issues/316).

## Objective and current phase

Develop and qualify the methodology on available free-tier cloud resources,
then use the same runner, task contracts, independent verifiers and evidence
reduction on the local estate. Public CPU and hosted platform experiments prove
specific mechanisms and measurement procedures; they do not establish physical
Metal/CUDA performance or production actor competence.

The primary outcome is independently accepted work within a stated resource,
latency and quality envelope. Operational campaign goodput counts accepted
unique deliverables once and divides by elapsed campaign time. Failed attempts,
retries, queueing, model loading, validation and recovery retain their costs.
Repeated synthetic successes are useful controlled observations, not unique
production deliverables. Summed per-arm lifecycle time is a different denominator
from campaign makespan and must be named explicitly.

The configured candidate remains task × harness artifact × model representation
× effective configuration × tools × runtime/route × substrate × authority.
Availability, successful installation and API health are separate evidence axes
from task qualification.

## Findings driving the next work

The strict ISH successor [PR #433](https://github.com/SemperSupra/model-spelunker/pull/433),
[run 46086572682](https://github.com/SemperSupra/model-spelunker/actions/runs/46086572682),
completed six public Linux jobs. Independent review rehashed six archives and
checked 18 canonical receipt/configuration/task/output joins and 36 persisted
request witnesses. The tested head is
`c70f29d116097695edff6fbcf4ddf6741c0242bc`; the tested merge is
`2e4e9eff2159731d81002716d9083f931a5a05b6`.

| Unchanged task | Resident | Cold restart | Native restore |
| --- | ---: | ---: | ---: |
| `text-repair-v0` | 3/3 accepted; 29.454967 s | 3/3; 44.528793 s | 3/3; 34.586962 s |
| `validation-discovery-v0` | 0/3 accepted; 34.847489 s | 0/3; 55.488614 s | 0/3; 39.801197 s |

Times sum three full per-arm lifecycles. Text repair's restore treatment used
22.33% less lifecycle time than cold restart. Residency used 14.84% less than
restore. Discovery's accepted goodput was zero for every treatment. Each failed
attempt listed files once, then voluntarily stopped after two model calls
without a read or required output write. Increasing only the four-call ceiling
does not address a voluntary stop before that ceiling.

All 18 observed recovery boundaries completed with expected native reuse.
Second-request message projections match within each task after call-ID
normalization; complete raw/tokenized-request equality remains unproven. Raw
native state, logs and SSE bytes were not retained. The frozen causal matcher
does not check the full preceding-message prefix; the archived requests preserve
it under independent inspection. Original declarations also have schema defects
that do not disappear when their byte hashes and behavioral joins match.

Detailed result and limitations:
[#316 terminal reconciliation](https://github.com/SemperSupra/model-spelunker/issues/316#issuecomment-7239762107).

The architectural implication is twofold: improve task completion before
optimizing repeated failure; preserve residency through short tool gaps when
resources permit, and measure checkpointing when eviction or restart makes it
useful. Neither result establishes a general local retention policy.

## Implemented candidate and qualification design

The opt-in `required-files-v1` completion check uses the existing OpenWorker
`TurnEngine.queue_steering()` seam. At a completed, no-tool `stop`, it may add one
message identifying explicitly required files that remain absent. It continues
the same engine generator and transcript within the original iteration and wall
budget. Errors, denials, interruption, truncation, unparsed tool protocol, exhausted
budget and unsafe paths do not qualify for continuation.

Required outputs are declared separately from allowed writes and must be a
subset of those writes. The check never reads output contents or the semantic
verifier. Existing incorrect contents remain for the unchanged external oracle
to reject. The default is `none`; there is no fleet-wide behavior change.

The [experiment procedure](../qualification/serving_fanout_r0/completion_guard_r0/README.md)
freezes a resident-only paired screen: three blocks, two unchanged tasks, guard
off/on, twelve attempts. It retains the admitted harness, exact model/server
pins, four-call limit, 256-token output limit, tools, seed and native settings.
Each arm uses a fresh server process and retains every outcome and lifecycle
cost. Native-loop tests with a scripted provider precede actual model inference.
Source/configuration, schema, receipt and output checks precede interpretation.

The receipt schema also now accepts `provider_finish_reason_counts`, which the
canonical runner already emitted. Counts remain nonnegative integers and missing
observations stay absent. New experiment declarations use valid v2 fields;
historical artifacts remain unchanged. This is a measurement-contract repair,
not a change to historical task acceptance.

The candidate is not a measured goodput gain until the paired results support
one. A zero-gain or regressing result is a valid stopping outcome. Do not enlarge
the budget, expose a known answer or change the oracle to make it pass.

## Prioritized methodology roadmap

| Priority | Work cell | Free-cloud proof | Later local discriminating test |
| --- | --- | --- | --- |
| P0 | Completion and useful actor baseline | Bounded continuation screen; protocol/negative controls; unchanged external oracle | Same portable tasks on an existing competent coding model and eligible direct harness, then one real backlog task |
| P0 | Effective configuration and honest costs | Bind all actual budgets, native flags, source and artifacts; validate schemas; retain failed and unstarted work | Fresh observed runtime/profile join; unique deliverables, verification, retries and operator effort |
| P1 | Context/cache/residency | Validate lifecycle accounting, isolation, prefix causality, save/restore/failure paths | Same model/task with short-context profiles and measured cache budgets; retain a separate long-context path |
| P1 | Exact runtime feature fit | Native parser, streaming, tool/result, cancellation and state compatibility controls | Current versus pinned candidate binary with identical weights/settings; confirm actual kernels, offload and memory behavior |
| P1 | Capacity and interactive reserve | Seeded mixed arrivals/tool delays, bounded queues, all-outcome accounting and fair-share negative controls | Concurrency 1/2/4/8 only where feasible; maximize accepted work subject to interactive latency/quality constraints |
| P2 | Evidence-aware advisory | Purpose admission and exact artifact/interview joins; truthful UNKNOWN and route semantics | Shadow recommendations from task-conditioned envelopes before managed placement |
| P2 | Harness refresh | Reproducible build/admission and no-model protocol tests, then sparse same-model/task crossover | Promote only the harness × model × task combinations that earn a better useful-work envelope |

Keep the existing ownership split: Foundry owns immutable artifact provenance;
IaC owns native resources and runtime profiles; Model Spelunker owns experiment
and task evidence; Model Compass consumes advisory evidence; Agent Dispatch owns
managed admission. Direct execution remains possible without requiring managed
placement. No additional scheduler, agent runner, registry or obligatory proxy
is required by this plan.

## Census-driven transfer

Use the latest accepted private estate census and its supplemental runtime
observations to select target profiles. Keep private inventory and endpoints
out of public fixtures. Model aliases, installed artifacts, running processes,
loaded weights and task-qualified candidates are different states.

The transfer procedure is:

1. Resolve the exact census campaign, immutable runtime/model/harness identities,
   current host generation and resource limits; refresh facts that have aged.
2. Bind an actor-neutral substrate profile to the existing portable launch
   procedure. Keep the task, independent oracle and evidence semantics unchanged.
3. Run the inexpensive deterministic/native protocol controls before model work.
4. Establish a useful resident baseline. Keep baseline failures as evidence;
   do not multiply recovery/concurrency treatments for a task-incompetent actor.
5. Change one justified factor, pair/interleave with the same-run baseline, and
   measure every attempt. Screen cheaply; confirm only finalists on held-out work.
6. Admit performance claims only for the observed target envelope. Source
   installation, method qualification and production promotion remain distinct.

For unified-memory Metal targets, the discriminating measurements include actual
context/cache allocations, model and projector/draft residency, page-ins and
memory pressure. For dual discrete GPUs, include single-device fit versus spread
or replicas, exact offload and topology, CPU/cgroup limits and competing workloads.
These are target-specific measurements to perform later, not numbers to infer
from public CPU experiments.

## Integration and ownership queue

Model Compass currently checks venue health before applying request filters.
Filtering before probes could avoid irrelevant timeout latency, but the shared
`main.go` remains reserved by the [#301 source disposition](https://github.com/SemperSupra/model-spelunker/issues/301#issuecomment-7093953264)
and [#303 route semantics](https://github.com/SemperSupra/model-spelunker/issues/303).
Resolve that integration queue before a competing core edit. Catalog task/TPS
scores and HTTP reachability are not task-qualified goodput estimates.

Harness refresh [#276](https://github.com/SemperSupra/model-spelunker/issues/276)
and the existing workbench/accounting drafts should be consolidated by evidence,
not replaced with another experimental framework. ISI remains deferred under
the [ISH evidence index](ish-qualification.md).
