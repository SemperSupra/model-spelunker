#!/usr/bin/env python3
"""Public-safe deterministic OCR qualification without model downloads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont

from visual_concept_worker_core import BackendScore, CandidateSpec, canonical_digest
from visual_concept_worker_deterministic import TesseractTextRecognizer, run_deterministic


class FakeScorer:
    family = "stub"
    model_id = "public/fake-scorer"
    model_revision = "v1"

    def score(self, image_path, concepts):
        return [BackendScore("document", "content.document", 1.0, 1.0)]


def make_fixture(path: Path) -> None:
    image = Image.new("RGB", (1800, 360), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 100)
    draw.text((60, 100), "HELLO 123 AUSGANG B7", fill="black", font=font)
    image.save(path)


def candidate() -> CandidateSpec:
    concepts = [{"label": "document", "concept_id": "content.document"}]
    return CandidateSpec(
        worker_framework="visual-concept-worker",
        framework_version="0.1.0",
        backend_family="stub",
        model_id="public/fake-scorer",
        model_revision="v1",
        concept_pack_digest=canonical_digest(concepts),
        action_policy="deterministic-v0",
        toolset=("score_concepts", "ocr"),
        parameters={
            "crop_strategy": "none",
            "ocr_strategy": "whole-v0",
            "ocr_engine": "tesseract",
            "ocr_languages": "eng+deu",
            "ocr_psm": 6,
            "top_k_per_view": 1,
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    concepts = [{"label": "document", "concept_id": "content.document"}]
    recognizer = TesseractTextRecognizer(languages="eng+deu", psm=6)
    with TemporaryDirectory(prefix="vcw-ocr-ringer-") as tmp:
        image_path = Path(tmp) / "ocr-fixture.png"
        make_fixture(image_path)
        kwargs = dict(
            scorer=FakeScorer(),
            candidate=candidate(),
            image_path=image_path,
            concepts=concepts,
            text_recognizer=recognizer,
            execution_lane="public-ringer",
        )
        first = run_deterministic(**kwargs)
        second = run_deterministic(**kwargs)

    ocr = [
        item for item in first["observations"]
        if item["evidence"][0]["kind"] == "ocr_text"
    ]
    if len(ocr) != 1:
        raise SystemExit(f"expected one whole-image OCR observation, got {len(ocr)}")
    text = ocr[0]["evidence"][0]["text_span"].upper()
    for token in ("HELLO", "123", "AUSGANG", "B7"):
        if token not in text:
            raise SystemExit(f"OCR missing expected token {token!r}: {text!r}")
    if first["run_digest"] != second["run_digest"]:
        raise SystemExit("OCR treatment run digest is not reproducible")

    try:
        run_deterministic(
            scorer=FakeScorer(),
            candidate=candidate(),
            image_path=Path(__file__),
            concepts=concepts,
            text_recognizer=None,
            execution_lane="public-ringer",
        )
    except ValueError as exc:
        if "no text_recognizer" not in str(exc):
            raise
    else:
        raise SystemExit("enabled OCR failed to reject missing text_recognizer")

    result = {
        "schema_version": "visual_concept_worker_ocr_ringer.v0.1",
        "status": "pass",
        "ocr_text": text,
        "run_digest": first["run_digest"],
        "observations": len(first["observations"]),
        "invariants": {
            "real_tesseract_executed": True,
            "reproducible_run_digest": True,
            "missing_runtime_rejected": True,
            "ground_truth_claimed": False,
            "private_content_present": False,
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
