#!/usr/bin/env python3
"""Public-safe zero-shot image tagging ringer.

This utility is intentionally generic. It consumes only public-safe images and a
public-safe candidate vocabulary. Private benchmark images, private ontologies,
human labels, and acceptance truth do not belong in this public runner.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import torch
from PIL import Image
from transformers import AutoModelForZeroShotImageClassification, AutoProcessor


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256_bytes(payload)


def load_image(source: str) -> tuple[Image.Image, bytes, str]:
    if source.startswith("https://"):
        response = requests.get(source, timeout=45)
        response.raise_for_status()
        raw = response.content
        locator_kind = "public_https"
    else:
        path = Path(source)
        raw = path.read_bytes()
        locator_kind = "local_path"
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    return image, raw, locator_kind


def transform_scores(logits: torch.Tensor, transform: str) -> torch.Tensor:
    if transform == "softmax":
        return torch.softmax(logits, dim=0)
    if transform == "sigmoid":
        return torch.sigmoid(logits)
    if transform == "raw":
        return logits
    raise SystemExit(f"unsupported score_transform: {transform}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    model_id = config["model_id"]
    model_revision = config.get("model_revision")
    image_source = config["image_source"]
    labels = list(config["candidate_labels"])
    templates = list(config.get("prompt_templates", ["a photo of a {}"] ))
    top_k = int(config.get("top_k", min(5, len(labels))))
    score_transform = str(config.get("score_transform", "softmax"))

    if not labels:
        raise SystemExit("candidate_labels must be non-empty")
    if not templates:
        raise SystemExit("prompt_templates must be non-empty")
    if top_k < 1:
        raise SystemExit("top_k must be >= 1")

    image, raw, locator_kind = load_image(image_source)

    processor = AutoProcessor.from_pretrained(model_id, revision=model_revision)
    model = AutoModelForZeroShotImageClassification.from_pretrained(model_id, revision=model_revision)
    model.eval()

    template = templates[0]
    prompts = [template.format(label) for label in labels]
    inputs = processor(text=prompts, images=image, return_tensors="pt", padding=True)

    with torch.inference_mode():
        outputs = model(**inputs)

    logits = outputs.logits_per_image[0].float()
    scores = transform_scores(logits, score_transform)
    ranked = torch.argsort(scores, descending=True).tolist()

    predictions = []
    for rank, idx in enumerate(ranked[:top_k], start=1):
        predictions.append({
            "rank": rank,
            "label": labels[idx],
            "prompt": prompts[idx],
            "score": float(scores[idx].item()),
            "raw_logit": float(logits[idx].item()),
        })

    result = {
        "schema_version": "image_auto_tag_public_ringer.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "kind": locator_kind,
            "sha256": sha256_bytes(raw),
            "width": image.width,
            "height": image.height,
        },
        "run": {
            "model_id": model_id,
            "model_revision": model_revision,
            "prompt_template": template,
            "score_transform": score_transform,
            "vocabulary_digest": canonical_digest(labels),
            "config_digest": canonical_digest(config),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "platform": platform.platform(),
            "device": "cpu",
        },
        "predictions": predictions,
        "safeguards": {
            "ground_truth": False,
            "human_review_status": "unreviewed",
            "private_benchmark_content_present": False,
            "private_semantic_authority_present": False,
        },
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "source_sha256": result["source"]["sha256"],
        "model_id": model_id,
        "score_transform": score_transform,
        "top": predictions[:3],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
