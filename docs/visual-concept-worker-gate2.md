# Visual Concept Worker Gate 2

Gate 2 is a controlled ablation between the proven `direct-v0` baseline and a
fixed, non-agentic `deterministic-v0` crop treatment.

Both treatments use the same public image bytes, concept pack, model family,
model revision, prompt template, score transform, and execution environment. The
only treatment difference is acquisition policy: direct-v0 scores the whole
image once; deterministic-v0 scores the same whole image plus four fixed
quadrants.

The gate passes only if the deterministic treatment preserves the direct
whole-image labels and scores, emits region-grounded additional evidence, keeps
candidate identities distinct, and makes no ground-truth or private-semantic
claim. Wall-clock time is recorded only as execution telemetry; it is not part
of the content-addressed worker identity.

This gate deliberately excludes OCR, detectors, segmentation, fusion, learned
planning, private benchmark images, and private semantic authority. Those remain
separate treatments so any gain can be attributed rather than conflated.
