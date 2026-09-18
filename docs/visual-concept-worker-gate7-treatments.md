# Visual Concept Worker Gate 7 — treatment comparison

Gate 7 applies direct-v0, deterministic-v0, and active-v0 to the identical
four-image Open Images workload established by Gate 6.

The model revision, concept pack, prompt template, score transform, input bytes,
and external human-verification scope are held constant. Only the acquisition
policy changes:

- direct: whole image only;
- deterministic: whole image plus four fixed quadrants;
- active: whole image plus at most one center crop when the observed top-2
  model-score margin is below the candidate-declared threshold.

Because the worker emits candidate evidence rather than thresholded class
decisions, the evaluation protocol is also explicit and identical across all
three candidates: take the maximum CLIP raw logit for each concept across the
visual evidence that candidate acquired, then compare human-verified positives
against human-verified negatives by ranking.

This measures the evidence-acquisition treatment, not policy correctness. It
does not claim that a four-image integration slice represents Open Images as a
whole. Model-view counts and elapsed time are retained as resource telemetry so
additional perception work can be evaluated against its cost.
