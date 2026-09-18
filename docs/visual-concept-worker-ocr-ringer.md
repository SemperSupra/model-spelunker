# Visual Concept Worker OCR Ringer

This ringer qualifies the deterministic OCR treatment independently from visual
model inference. It uses a generated public-safe text fixture, a stub visual
scorer, and the real Tesseract runtime with English and German language packs.

The gate checks four things that matter to the worker contract:

- OCR is enabled only when the candidate declares the `ocr` tool and strategy;
- a missing OCR runtime adapter fails closed instead of silently skipping OCR;
- OCR evidence records the Tesseract runtime version, language set, and PSM;
- repeating the same treatment over the same bytes yields the same run digest.

The fixture is generated inside the runner and contains only synthetic text.
No private media, private benchmark labels, credentials, policy authority, or
model downloads are involved.

This is a runtime/integration qualification only. Recognizing the synthetic text
is not evidence of general OCR accuracy.
