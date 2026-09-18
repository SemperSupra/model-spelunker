# Visual Concept Worker Gate 10 — model substitution

Gate 10 tests the model-substitution seam at a more useful scale while holding
the worker treatment fixed at direct-v0.

Pinned CLIP and SigLIP candidates process the identical 24-image Open Images
validation slice, the same external human-verified positive/negative annotations,
and the same concept IDs. Each model receives its already-qualified prompt and
score transform.

Evaluation is within-model ranking only: one whole-image raw score per concept is
used to compare verified positives with verified negatives. CLIP and SigLIP raw
score magnitudes are never compared to one another because their scoring
semantics differ.

The result can therefore compare task metrics and resource telemetry between the
configured model candidates without pretending their raw confidence scales are
interchangeable. The 24-image slice remains a bounded qualification sample, not
a representative estimate of either model or Open Images as a whole.
