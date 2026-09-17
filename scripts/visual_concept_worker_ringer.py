#!/usr/bin/env python3
"""Public-safe Gate-1 ringer for the visual concept worker direct-v0 control."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import tempfile
from typing import Any, Sequence

import requests
import torch
from PIL import Image
from transformers import AutoModelForZeroShotImageClassification, AutoProcessor

from visual_concept_worker_core import BackendScore, CandidateSpec, canonical_digest, run_direct


class PublicHFScorer:
    def __init__(self, config: dict[str, Any]) -> None:
        self.family = config["backend_family"]
        self.model_id = config["model_id"]
        self.model_revision = config.get("model_revision")
        self.prompt_template = config.get("parameters", {}).get("prompt_template", "a photo of a {}")
        self.score_transform = config.get("parameters", {}).get("score_transform", "softmax")
        self.text_padding = config.get("parameters", {}).get("text_padding", True)
        self.processor = AutoProcessor.from_pretrained(self.model_id, revision=self.model_revision)
        self.model = AutoModelForZeroShotImageClassification.from_pretrained(self.model_id, revision=self.model_revision)
        self.model.eval()

    def _transform(self, logits: torch.Tensor) -> torch.Tensor:
        if self.score_transform == "softmax":
            return torch.softmax(logits, dim=0)
        if self.score_transform == "sigmoid":
            return torch.sigmoid(logits)
        if self.score_transform == "raw":
            return logits
        raise ValueError(f"unsupported score transform: {self.score_transform}")

    def score(self, image_path: str | Path, concepts: Sequence[dict[str, Any]]) -> Sequence[BackendScore]:
        image = Image.open(image_path).convert("RGB")
        labels = [str(item["label"]) for item in concepts]
        prompts = [self.prompt_template.format(label) for label in labels]
        inputs = self.processor(text=prompts, images=image, return_tensors="pt", padding=self.text_padding)
        with torch.inference_mode():
            outputs = self.model(**inputs)
        logits = outputs.logits_per_image[0].float()
        scores = self._transform(logits)
        return [
            BackendScore(
                label=labels[i],
                concept_id=concepts[i].get("concept_id"),
                score=float(scores[i].item()),
                raw_score=float(logits[i].item()),
                metadata={"prompt": prompts[i], "score_transform": self.score_transform},
            )
            for i in range(len(labels))
        ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if cfg.get("public_safe") is not True:
        raise SystemExit("ringer config must explicitly set public_safe=true")
    concepts = cfg["concepts"]
    concept_pack_digest = canonical_digest(concepts)
    candidate = CandidateSpec(
        worker_framework=cfg["worker_framework"],
        framework_version=cfg["framework_version"],
        backend_family=cfg["backend_family"],
        model_id=cfg["model_id"],
        model_revision=cfg.get("model_revision"),
        concept_pack_digest=concept_pack_digest,
        action_policy=cfg.get("action_policy", "direct-v0"),
        toolset=tuple(cfg.get("toolset", ["score_concepts"])),
        parameters=dict(cfg.get("parameters", {})),
    )

    response = requests.get(cfg["image_source"], timeout=45)
    response.raise_for_status()
    raw = response.content
    with tempfile.TemporaryDirectory() as tmpdir:
        image_path = Path(tmpdir) / "public-fixture.png"
        image_path.write_bytes(raw)
        scorer = PublicHFScorer(cfg)
        result = run_direct(
            scorer=scorer,
            candidate=candidate,
            image_path=image_path,
            concepts=concepts,
            top_k=int(candidate.parameters.get("top_k", 5)),
            execution_lane="public-ringer",
        )

    result["public_ringer"] = {
        "public_safe": True,
        "private_benchmark_content_present": False,
        "private_semantic_authority_present": False,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_digest": result["candidate"]["candidate_digest"],
        "input_sha256": result["input"]["sha256"],
        "top": [x["label"] for x in result["observations"][:3]],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
