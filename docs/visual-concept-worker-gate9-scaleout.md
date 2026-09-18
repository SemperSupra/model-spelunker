# Visual Concept Worker Gate 9 — 24-image treatment scale-out

Gate 9 repeats the Gate-7 experiment without changing the candidates or active
policy, but expands the deterministic Open Images validation selection from four
images to the first 24 complete image groups that each contain at least two
human-verified positives and two human-verified negatives.

The same pinned CLIP revision, prompts, score transform, positive/negative label
selection, and best-acquired-raw-evidence ranking protocol are retained. The
experiment therefore checks whether the Gate-7 result survives a moderately
larger workload before any active-policy tuning is permitted.

The three treatments remain:

- direct-v0: one whole-image view;
- deterministic-v0: whole image plus four fixed quadrants;
- active-v0: whole image plus at most one observation-triggered center crop.

This is still a bounded integration/qualification sample, not a representative
estimate for Open Images and not a policy-accuracy benchmark. Image bytes are
public dataset media and are used ephemerally; no private benchmark content is
involved.
