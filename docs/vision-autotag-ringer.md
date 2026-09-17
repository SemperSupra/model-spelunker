# Vision auto-tag public ringer

Status: public-safe CPU qualification lane.

## Purpose

Exercise a zero-shot visual tagging harness on standard GitHub-hosted Actions using only public-safe inputs and public-safe vocabulary. This lane proves that the model/runtime/harness works on the free public-repository runner before the same analyzer is used against private benchmark material on a trusted lane.

## Privacy/value boundary

The public ringer must never consume:

- private benchmark images or crops;
- private Google Drive URLs/tokens;
- private CPE vocabulary, human labels, adjudicated gold labels, or research hypotheses;
- private repository credentials;
- private result corpora.

The checked-in configuration uses a public Hugging Face documentation image and a generic vocabulary. Output is diagnostic only and is not ground truth.

## Model

The first ringer uses `openai/clip-vit-base-patch32` through Hugging Face Transformers on CPU. The model is intentionally treated as a candidate analyzer rather than policy authority.

## Execution

The workflow runs on `ubuntu-latest`, installs CPU-only PyTorch and pinned user-space dependencies, downloads the public model, runs one public image through a small candidate vocabulary, and fails if a parrot/bird label is not top-ranked.

No Actions artifact is uploaded and no dependency/model cache is retained. This keeps persistent public-repository storage near zero. Model download time is accepted for the first reps; caching must earn its keep before being introduced.

## Relationship to the private benchmark

The private benchmark stores four separate evidence layers:

1. seed labels;
2. automated analyzer observations;
3. human labels;
4. adjudicated gold labels.

The public ringer validates the analyzer implementation only. Private image inference happens on a trusted local/self-hosted lane unless a separate, explicitly qualified confidential-input execution path is adopted.

For public-safe experiments that need confidential result return, reuse the existing `SemperSupra/agent-dispatch` sealed-public-execution primitive rather than inventing another result-transport protocol.
