#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import requests
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import AutoModelForZeroShotImageClassification, AutoProcessor


EXPECTED_IMAGE_SHA256 = "d14e9adf584087f478dc9231c64caf6631d363dfd2188b10a4bd1c0a4020d082"


def tensor_metrics(cpu: torch.Tensor, mps: torch.Tensor) -> dict:
    a = cpu.detach().float().cpu()
    b = mps.detach().float().cpu()
    if tuple(a.shape) != tuple(b.shape):
        return {"shape_cpu": list(a.shape), "shape_mps": list(b.shape), "shape_match": False}
    flat_a = a.reshape(-1)
    flat_b = b.reshape(-1)
    abs_diff = (flat_a - flat_b).abs()
    denom = flat_a.norm().item()
    rel_l2 = (flat_a - flat_b).norm().item() / denom if denom else None
    cos = F.cosine_similarity(flat_a.unsqueeze(0), flat_b.unsqueeze(0), dim=1).item()
    return {
        "shape_cpu": list(a.shape),
        "shape_mps": list(b.shape),
        "shape_match": True,
        "cosine_similarity": cos,
        "max_abs_diff": abs_diff.max().item() if abs_diff.numel() else 0.0,
        "mean_abs_diff": abs_diff.mean().item() if abs_diff.numel() else 0.0,
        "relative_l2": rel_l2,
    }


def row_cosines(cpu: torch.Tensor, mps: torch.Tensor) -> list[float]:
    a = cpu.detach().float().cpu()
    b = mps.detach().float().cpu()
    if a.ndim != 2 or b.ndim != 2 or a.shape != b.shape:
        return []
    return F.cosine_similarity(a, b, dim=1).tolist()


def rank_labels(values: torch.Tensor, labels: list[str]) -> list[str]:
    row = values.detach().float().cpu().reshape(-1)
    order = torch.argsort(row, descending=True).tolist()
    return [labels[i] for i in order]


def normalized_similarity(image_embeds: torch.Tensor, text_embeds: torch.Tensor) -> torch.Tensor:
    image = F.normalize(image_embeds.detach().float().cpu(), dim=-1)
    text = F.normalize(text_embeds.detach().float().cpu(), dim=-1)
    return image @ text.T


def extract(outputs):
    required = {}
    for name in ("image_embeds", "text_embeds", "logits_per_image"):
        value = getattr(outputs, name, None)
        if value is None:
            raise RuntimeError(f"model output missing {name}")
        required[name] = value
    return required


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--runner-label", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    assert cfg.get("public_safe") is True
    if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
        raise SystemExit("MPS unavailable")
    if str(Path(args.output)).strip() == "":
        raise SystemExit("output path required")

    response = requests.get(cfg["image_source"], timeout=45)
    response.raise_for_status()
    raw = response.content
    image_sha = hashlib.sha256(raw).hexdigest()
    if image_sha != EXPECTED_IMAGE_SHA256:
        raise RuntimeError(f"fixture drift: {image_sha}")

    labels = [str(x["label"]) for x in cfg["concepts"]]
    prompts = [
        cfg.get("parameters", {}).get("prompt_template", "a photo of a {}").format(label)
        for label in labels
    ]
    padding = cfg.get("parameters", {}).get("text_padding", True)

    processor = AutoProcessor.from_pretrained(cfg["model_id"], revision=cfg.get("model_revision"))
    model = AutoModelForZeroShotImageClassification.from_pretrained(
        cfg["model_id"],
        revision=cfg.get("model_revision"),
    )
    model.eval()

    with tempfile.TemporaryDirectory(prefix="vcw-mps-localize-") as td:
        image_path = Path(td) / "fixture.png"
        image_path.write_bytes(raw)
        image = Image.open(image_path).convert("RGB")
        cpu_inputs = processor(text=prompts, images=image, return_tensors="pt", padding=padding)

        with torch.inference_mode():
            cpu_outputs = extract(model(**cpu_inputs))

        cpu = {k: v.detach().float().cpu() for k, v in cpu_outputs.items()}

        model.to("mps")
        mps_inputs = {
            k: (v.to("mps") if isinstance(v, torch.Tensor) else v)
            for k, v in cpu_inputs.items()
        }
        with torch.inference_mode():
            raw_mps = extract(model(**mps_inputs))
            torch.mps.synchronize()
        mps = {k: v.detach().float().cpu() for k, v in raw_mps.items()}

    cpu_cos = normalized_similarity(cpu["image_embeds"], cpu["text_embeds"])
    mps_cos = normalized_similarity(mps["image_embeds"], mps["text_embeds"])

    cpu_logits_rank = rank_labels(cpu["logits_per_image"], labels)
    mps_logits_rank = rank_labels(mps["logits_per_image"], labels)
    cpu_cos_rank = rank_labels(cpu_cos, labels)
    mps_cos_rank = rank_labels(mps_cos, labels)

    result = {
        "schema_version": "visual_concept_mps_localization.v1",
        "runner_label": args.runner_label,
        "backend_family": cfg["backend_family"],
        "model_id": cfg["model_id"],
        "model_revision": cfg.get("model_revision"),
        "torch": torch.__version__,
        "mps": {
            "built": bool(torch.backends.mps.is_built()),
            "available": bool(torch.backends.mps.is_available()),
            "fallback_env": __import__("os").environ.get("PYTORCH_ENABLE_MPS_FALLBACK"),
            "model_device": str(next(model.parameters()).device),
        },
        "fixture": {
            "sha256": image_sha,
            "labels": labels,
            "prompts": prompts,
            "expected_top_labels": cfg["expected_top_labels"],
        },
        "rankings": {
            "cpu_logits": cpu_logits_rank,
            "mps_logits": mps_logits_rank,
            "cpu_recomputed_cosine": cpu_cos_rank,
            "mps_recomputed_cosine": mps_cos_rank,
        },
        "comparisons": {
            "image_embeds": tensor_metrics(cpu["image_embeds"], mps["image_embeds"]),
            "text_embeds": tensor_metrics(cpu["text_embeds"], mps["text_embeds"]),
            "text_embed_row_cosines": row_cosines(cpu["text_embeds"], mps["text_embeds"]),
            "logits_per_image": tensor_metrics(cpu["logits_per_image"], mps["logits_per_image"]),
            "recomputed_cosine": tensor_metrics(cpu_cos, mps_cos),
        },
        "raw": {
            "cpu_logits": cpu["logits_per_image"].reshape(-1).tolist(),
            "mps_logits": mps["logits_per_image"].reshape(-1).tolist(),
            "cpu_recomputed_cosine": cpu_cos.reshape(-1).tolist(),
            "mps_recomputed_cosine": mps_cos.reshape(-1).tolist(),
        },
    }

    if cpu_logits_rank[0] not in cfg["expected_top_labels"]:
        raise RuntimeError(f"CPU semantic control failed: {cpu_logits_rank}")
    if result["mps"]["fallback_env"] != "0":
        raise RuntimeError("MPS fallback must be disabled")
    if not result["mps"]["model_device"].startswith("mps"):
        raise RuntimeError(f"model not on MPS: {result['mps']['model_device']}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("MPS_LOCALIZATION=" + json.dumps({
        "runner": args.runner_label,
        "backend": cfg["backend_family"],
        "cpu_top3": cpu_logits_rank[:3],
        "mps_top3": mps_logits_rank[:3],
        "image_cos": result["comparisons"]["image_embeds"].get("cosine_similarity"),
        "text_cos_min": min(result["comparisons"]["text_embed_row_cosines"]) if result["comparisons"]["text_embed_row_cosines"] else None,
        "logit_cos": result["comparisons"]["logits_per_image"].get("cosine_similarity"),
        "recomputed_cos_rank_mps": mps_cos_rank[:3],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
