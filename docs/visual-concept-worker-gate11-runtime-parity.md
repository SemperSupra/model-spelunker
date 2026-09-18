# Visual Concept Worker Gate 11 — private runtime parity

The public qualification workflows originally used Transformers 5.17.0, while
the private analyzer package currently declares `transformers>=4.48,<5`. Before
the trusted 47-image sweep, Gate 11 checks that the same pinned CLIP and SigLIP
candidates also execute correctly inside a runtime that is compatible with the
private package constraint.

The gate fixes:

- Python 3.12
- PyTorch 2.14.0 CPU
- Transformers 4.57.1
- Pillow 12.3.0
- sentencepiece 0.2.2
- protobuf 7.36.1

Both direct-v0 candidates must preserve the existing public-ringer contract and
expected top-label behavior on the same public-safe fixture.

If this passes, the private sweep can use a reproducible environment inside the
current package dependency envelope rather than changing the package-wide
Transformers constraint immediately.
