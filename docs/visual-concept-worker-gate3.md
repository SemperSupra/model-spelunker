# Visual Concept Worker Gate 3

Gate 3 is the first real-model integration of the bounded active controller. It
does not attempt to prove that active perception improves accuracy.

All three treatments use the same public image bytes, concept pack, pinned CLIP
model revision, prompt template, score transform, and runner:

- `direct-v0`: one whole-image model view;
- `deterministic-v0`: the whole image plus four fixed quadrants;
- `active-v0`: the identical direct evidence followed by at most one crop probe
  when the observed top-2 score margin is below the candidate-declared threshold.

The active gate passes only if the decision is observation-dependent, the action
budget and toolset are candidate-bound, the probe evidence is region-grounded,
the initial direct evidence is preserved exactly, and repeated active execution
produces the same worker and execution digests.

Model-view counts and wall-clock values are descriptive resource telemetry only.
This single public fixture makes no accuracy, superiority, or policy-quality
claim. Private media and private semantic authority remain outside the runner.
