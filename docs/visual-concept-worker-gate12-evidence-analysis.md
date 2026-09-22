# Visual Concept Worker Gate 12 — No-gold evidence analysis

Gate 12 qualifies descriptive analysis and repeatability comparison without using
seed references, human review, adjudicated truth, or candidate ranking.

The analyzer accepts one or more visual batch manifests and reports only
structural observations:

- candidate emission counts and assertion/evidence-kind counts;
- per-asset concept unions, intersections, and disagreements;
- pairwise concept-set overlap/difference counts;
- per-concept asset-frequency by candidate;
- OCR-associated evidence presence;
- missing/failed evidence;
- exact semantic duplicate groups.

These are descriptive properties of model outputs. They are not accuracy,
precision/recall, error-rate, or winner/loser claims.

The repeatability comparator binds candidate/treatment identity and input SHA-256,
then distinguishes:

1. stable result identity;
2. stable semantic observations with changed result identity;
3. semantic/input drift;
4. candidate/configuration drift.

It never normalizes semantic drift away merely to make two runs compare equal.

The public ringer uses generated synthetic manifests only. Private media, private
benchmark results, seed semantic authority, and human judgments are absent. The
qualified implementation may later be run on a trusted local/private evidence
set without changing these semantics.
