# rtl-fifo4-v1 fixture preparation

State: **prepared, not yet used for model inference**.

Purpose: provide one deterministic RTL task that is materially harder than the popcount canary without introducing a benchmark suite or subjective judge.

The fixed oracle covers synchronous reset, fill/drain, full and empty blocking, simultaneous operations, pointer wrap-around, and 96 deterministic pseudo-random cycles against an independent scoreboard.

This fixture is neutral with respect to controller or specialist implementation. The same specification and testbench must be used for baseline and specialist-augmented comparisons.

Execution remains gated on the RTLCoder popcount specialist-amplification result.
