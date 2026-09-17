# Visual Concept Worker public ringer

This ringer is the public-safe Gate-1 execution lane for the visual concept worker MVP.

It intentionally exercises only the non-agentic `direct-v0` control:

`public still image -> CLIP-compatible whole-image scorer -> evidence ledger -> run manifest`

The ringer uses only public media and a public generic concept pack. It does not consume private benchmark images, private CPE semantic authority, human labels, or credentials for private repositories/Drive content.

The purpose is implementation/runtime qualification, not concept or policy authority. Successful execution establishes that the worker contract, candidate identity, model backend, and evidence ledger run reproducibly on a public CPU GitHub-hosted runner. Later deterministic and active-perception treatments must compare against this baseline rather than silently replacing it.

Run identity is content-addressed for the stimulus: storage filenames remain useful metadata but are excluded from the reproducibility digest, so byte-identical media produce the same run digest under the same candidate and observations.

The workflow is deliberately bounded to one CLIP candidate. Additional models, tools, benchmark adapters, and matrix parallelism are added only after this seam passes and only when an experiment needs them.
