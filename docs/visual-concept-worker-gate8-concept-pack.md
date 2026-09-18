# Visual Concept Worker Gate 8 — concept packs

Gate 8 qualifies the concept-pack compatibility seam before the private 47-image
sweep.

The worker accepts the current `concepts[]` representation, the earlier
`labels[]` representation, or a direct list and normalizes them into one stable
`label + concept_id` sequence before candidate identity is computed. Equivalent
legacy/current structured packs must therefore produce the same normalized
digest.

The loader fails closed on ambiguous objects containing both `concepts` and
`labels`, empty packs, empty labels, duplicate labels, duplicate concept IDs,
and invalid entry types.

The public ringer intentionally uses only synthetic labels. The private
95-concept image-policy pack and its semantic authority do not cross into the
public runner.
