# Visual Concept Worker Gate 4

Gate 4 qualifies the batch/provenance layer before any 47-asset private model
run is attempted. The ringer uses only generated public-safe byte fixtures and a
fake result producer; real-model execution was already qualified in Gates 1–3.

The gate verifies nested benchmark asset identity, SHA-256 checks, content-addressed
per-asset output names, retained failures, continued execution after a bad asset,
and a stable batch digest that excludes volatile run IDs and timestamps.

The same batch module rejects public execution when `private_inputs=true`; this
public ringer must explicitly set `private_inputs=false`. Actual benchmark runs
therefore remain restricted to `trusted-local` or `trusted-self-hosted` lanes.
