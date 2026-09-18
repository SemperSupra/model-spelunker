# External visual benchmark adapters

This lane keeps external benchmark authority deliberately narrow.

For Open Images-style image-level labels, only explicitly human-verified
positive and negative annotations are eligible for scoring. Unannotated labels
remain unknown. External labels are translated through explicit mapping records:
only an `exact` mapping is eligible for exact presence metrics; `narrower`,
`broader`, `related`, and `excluded` mappings remain visible but unscored.
Those metrics apply only to the external dataset's declared task scope and do
not become CPE policy ground truth.

Crossmodal-3600 (XM3600) is treated as multilingual human caption/image
alignment evidence. The source contract points to the official Crossmodal-3600
project, caption download, image archive, and attribution metadata. Caption
annotations are CC BY 4.0; image licensing/attribution remains per-image and
must be preserved separately.

The XM3600 adapter normalizes common JSONL forms into
`image_id + language + human caption` and can build deterministic ranking
trials where references belong to the target image and decoys are captions from
different images in the same language. This supports later multilingual
visual-semantic qualification without pretending captions are CPE concept gold.
