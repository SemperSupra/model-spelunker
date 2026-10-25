# model-spelunker

Model Spelunker is an instrument-neutral framework for reverse engineering and characterizing unknown or poorly documented models through controlled probing, internal observation when available, and evidence-backed hypothesis testing.

The operational goal is not a single interpretability technique. It is a repeatable SOP/TTP stack that can answer, with explicit confidence and provenance:

- What behavior and capabilities does the model exhibit?
- What concepts and distinctions appear to be represented?
- Where and when do those representations emerge?
- Which representations are merely decodable versus causally involved?
- Which interaction protocols activate or suppress behaviors?
- What aspects of the recovered model generalize to unseen probes?
- Which conclusions are supported by observation, association, prediction, or intervention?

## Core design

Every experiment is expressed as a common `ProbeCase` and can be observed by multiple inspection instruments in parallel. Each instrument emits a standard `ObservationBundle` plus method-specific artifacts. This permits direct comparison of informativeness, agreement, contradictions, cost, and unique contribution across methods.

Initial instrument lanes:

1. black-box behavioral probing
2. fMRI-style activation cartography
3. logit/tuned-lens trajectory inspection
4. representational geometry and similarity analysis
5. learned probes
6. sparse feature/dictionary methods such as SAEs
7. attribution/circuit tracing
8. causal intervention: patching, ablation, and steering
9. natural-language activation decoding where supported

The fMRI-style lane remains a first-class experimental path, but is intentionally not privileged as the sole way to inspect a model.

## Evidence discipline

Claims progress through an explicit evidence ladder:

`OBSERVED -> REPRODUCED -> RELATIONAL -> PREDICTIVE -> CAUSAL/FUNCTIONALLY RECOVERED`

No instrument is allowed to promote a result beyond the evidence it actually provides. In particular, localization, correlation, decodability, and causal contribution are recorded as different claim types.

## Repository direction

See:

- `docs/method-portfolio.md` — parallel instrument lanes and comparison framework
- `docs/calibration.md` — model-organism and blind-recovery calibration strategy
- `schemas/probe-case.schema.json` — common experiment input contract
- `schemas/observation-bundle.schema.json` — common instrument output/evidence contract

The next implementation milestone is a runner that executes one `ProbeCase` against one model while dispatching all compatible instrument adapters and writing a single evidence bundle.