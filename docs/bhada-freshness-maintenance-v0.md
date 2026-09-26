# BHADA freshness-driven autonomous-maintenance proving campaign v0

Authority: SemperSupra/agent-dispatch-private#104 and SemperSupra/model-spelunker#132.

## Decision question

Does freshness/staleness-driven autonomous maintenance produce enough useful operational work and qualification evidence to justify keeping the mechanism, without creating more compute/toil/false confidence than it removes?

This is a falsification campaign, not an architecture rollout.

## Governing invariants

- Self-description states claims; qualification/live evidence states observations.
- Expiry/context drift makes work eligible; it does not itself authorize immediate execution.
- Freshness, urgency, and value-of-revalidation remain separate.
- Provider/backend/readiness failure is not automatically actor failure.
- Repair actors may not weaken validators, widen authority, or redefine acceptance.
- Original actor output remains immutable qualification evidence.
- Product promotion is separate from qualification acceptance.
- Blind independent diagnosis precedes collaboration when diversity is being measured.
- Correlated manifestations of one upstream incident are not counted as independent semantic trials.
- Valid maintenance outcomes include revalidate unchanged, diagnose, repair, substitute, quarantine, retire, and preserve UNKNOWN.
- No scheduler, registry database, global score, dashboard, or learned optimizer is part of v0.

## Implementation plan

### Increment 0 — executable contract

Implement and validate:

1. a pure freshness/eligibility projection that distinguishes:
   - FRESH / STALE / INVALIDATED;
   - WORKING / DEGRADED / UPSTREAM_CHANGED / FAILED / readiness-blocked / UNKNOWN;
   - USE_EVIDENCE / REVALIDATE / RESTORE_READINESS / DIAGNOSE / OBSERVE;
   - NONE / OPPORTUNISTIC / DECISION_REQUIRED urgency.
2. a public-safe maintenance-triage interview task with an independent deterministic verifier;
3. one preregistered same-harness/different-model experiment using DeepSeek, Gemini, and GPT-OSS actors;
4. CI self-tests proving the classifier and verifier reject the most dangerous attribution errors.

Acceptance: contract tests pass and no product/release mutation occurs.

### Increment 1 — shadow live revalidation

Use existing BHADA LIVE/provider-health observations and Agent Dispatch source-observation work. Do not add a new polling service.

For each eligible event capture:
- component/evidence identity;
- observation age and applicability context;
- why refresh became eligible;
- urgency at the decision point;
- probe cost/wall time;
- outcome: unchanged/pass, changed/degraded, readiness-blocked, unknown;
- human interventions;
- resulting maintenance task, if any.

Prefer refresh-on-use or spare-capacity refresh. Do not trigger merely to satisfy a calendar if no decision/value exists.

Initial promotion sample: 10 eligible opportunities spanning at least 3 distinct components or failure contexts, unless earlier evidence falsifies the idea.

### Increment 2 — diagnosis interviews

When a live failure is fresh and reproducible:
- freeze a sanitized evidence package;
- run at least two materially different configured actors independently where cost/availability permits;
- keep first-pass outputs blind;
- independently validate failure-plane attribution, UNKNOWN preservation, and next-experiment quality;
- group correlated manifestations by incident/failure family.

Do not force a repair when diagnosis supports wait/substitute/quarantine/retire.

### Increment 3 — bounded repair

Only for failures whose diagnosis establishes a software-change hypothesis and whose authority permits mutation:
- generate the smallest repair;
- preserve actor C1 unchanged;
- validate against deterministic fixture/contract oracles plus bounded live canary where appropriate;
- use held-out/differential/property checks only when they catch a concrete plausible overfitting defect;
- promote to BHADA through its normal project acceptance path, never directly from qualification.

### Increment 4 — heterogeneous team reps

Only after individual evidence exists.

Candidate topology:
sensor/probe -> independent diagnosticians -> repair actor -> independent validator.

Promotion criterion for a team: measurable lift over the best useful individual on validated coverage, defect discovery, recovery, or cost/attention. More agents or more tokens is not itself lift.

## Deployment plan

### Plane A — public Model Spelunker

Purpose: public-safe task packages, actor profiles, immutable receipts, reducers, diversity/complementarity experiments.

No private BHADA source, credentials, cookies, or raw private observations are published.

### Plane B — BHADA

Purpose: authoritative product/live observation and eventual accepted repairs.

Reuse:
- stage-visible LIVE capability proof;
- provider_status_probe / canary behavior;
- deterministic provider/extractor fixtures;
- existing spelunk/forensics evidence where safe.

Do not create a parallel provider-health registry. Freshness receipts/sidecars are derived observations.

### Plane C — Agent Dispatch

Purpose: least-authority work issuance and continuation.

A stale observation may create an eligible bounded work cell. Binding/execution still depends on capability, readiness, authority, and resource evidence.

No generic scheduler is required. Agent Dispatch remains the actuator.

### Initial live deployment gate

BHADA #103 currently has self-hosted-runner readiness UNKNOWN/unavailable. Do not spam retries. The first live revalidation rep begins when the existing executor is actually ready or another already-authorized equivalent venue exists.

Until then, deterministic/public-safe contract reps continue without pretending they are live-provider evidence.

## Red team

Kill or narrow the mechanism if any of the following dominates:

- synchronized expiry creates refresh storms;
- >50% of shadow opportunities require human relay before producing an actionable classification;
- automation repeatedly creates issues/PRs/retries with no new information;
- validator/test overfitting produces false-green repairs;
- correlated upstream incidents inflate apparent qualification reliability;
- stale evidence is treated as failed evidence;
- readiness/provider/task-package failures leak into actor negatives;
- repair becomes the default even when substitute/quarantine/retire is cheaper;
- private data must be exposed to obtain qualification reps;
- the mechanism needs a scheduler/database/ontology before delivering measurable value.

Stop/replan after two materially different non-informative attempts on the same incident rather than retrying blindly.

## Blue team

Opportunities to retain if observed:

- cheap no-change revalidation permits shorter confidence horizons for volatile components;
- real maintenance supplies representative task diversity without benchmark-only spend;
- provider -> backend -> transport hierarchy enables cheapest-first validation;
- blind diagnosis produces measurable model/harness complementarity;
- live drift naturally expands the task-class catalog;
- failure attribution improves the qualification methodology itself;
- the same freshness/applicability semantics can later govern actor qualification evidence;
- empirical churn/cost data can support learned freshness policy later without implementing an optimizer now.

## Metrics

Operational:
- eligible refreshes;
- unchanged refreshes;
- material drift discoveries;
- readiness-blocked observations;
- diagnosis attempts;
- repair attempts and validated repairs;
- substitute/quarantine/retire outcomes;
- wall time and machine/API cost;
- human interventions;
- generated issue/PR/retry burden;
- time to actionable classification.

Scientific:
- exact configured-actor identity;
- semantic pass/fail/censored/incomplete;
- failure-attribution correctness;
- UNKNOWN preservation;
- unique valid contribution;
- pairwise error correlation;
- counterexample yield;
- blind-vs-collaborative delta;
- team lift over best useful individual;
- incident/failure-family correlation.

Freshness economics:
- evidence age when actually queried;
- no-change refresh rate;
- drift hazard by component/failure family;
- revalidation cost;
- repair frequency;
- false-stale and false-green observations.

## Go / hold / kill thresholds

After the first 10 eligible shadow opportunities:

GO to broader autonomous refresh if:
- at least 80% reach an actionable terminal classification without human relay;
- no false-green product promotion occurs;
- at least 2 opportunities either discover material drift, avoid a manual check, or generate qualification evidence that changes a placement/diversity decision;
- generated maintenance burden remains bounded (no retry/issue storm).

HOLD and gather more evidence if the sample is dominated by no-change observations but refresh cost is low and the decision value remains uncertain.

KILL generalized proactive refresh if:
- fewer than 2/10 opportunities produce operational or qualification value;
- human relay is required for more than half of opportunities;
- automation overhead/maintenance artifacts clearly exceed the avoided toil;
- correctness requires a central compatibility registry or broad new orchestration machinery.

Even after KILL, retain useful provider-specific/on-demand checks and immutable historical evidence.

## Current execution frontier

Implemented on child branch exp/bhada-freshness-maintenance-v0:
- deterministic freshness/eligibility projection;
- maintenance-triage-v0 interview task and verifier;
- three-actor preregistered diversity experiment.

Next:
1. run contract CI;
2. record results on Model Spelunker #132 / Agent Dispatch #104;
3. when BHADA execution readiness returns, consume the next eligible real LIVE observation as the first shadow rep;
4. do not authorize autonomous BHADA repair until shadow evidence earns Increment 3.
