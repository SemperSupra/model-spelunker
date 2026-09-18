# Visual Concept Worker Gate 5 — Review Queue

Gate 5 qualifies the comparison/review layer independently of model inference.

The review queue may compare automated candidates with each other and with seed
references, but it must not convert either source into ground truth. A concept
not observed by an automated candidate is not treated as absent. Seed/auto
differences and cross-candidate disagreement are retained only as human-review
cues.

The public ringer uses synthetic benchmark metadata and synthetic automated
observations. It verifies deterministic queue identity, disagreement retention,
novel-vs-seed cues, and the absence of manufactured accuracy claims. No private
media or private semantic authority is used.
