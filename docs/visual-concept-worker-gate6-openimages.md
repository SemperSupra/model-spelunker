# Visual Concept Worker Gate 6 — Open Images live slice

Gate 6 is the first real external-ground-truth model rep.

The gate streams the official Open Images V7 validation human image-level label
file, deterministically selects four complete image groups having at least two
human-verified positives and two human-verified negatives, downloads those four
validation images ephemerally, and scores a pinned CLIP direct-v0 candidate.

The worker still emits `candidate` observations. Gate 6 therefore does not invent
a classification threshold or silently promote candidates to `supported` facts.
Instead it evaluates score ordering only: human-verified positive labels are
compared against human-verified negative labels for the same image using
pairwise ranking, positive-at-k, and mean positive rank.

Only explicitly human-verified labels participate. Unannotated labels remain
unknown. Metrics apply only to Open Images image-level concept presence and do
not become CPE policy ground truth. The four-image slice is an integration rep,
not a representative population estimate.

Image bytes are downloaded only for the duration of the GitHub-hosted public
job and are not uploaded as artifacts. This lane uses public dataset media only;
private CPE benchmark images and private semantic authority remain excluded.
