#!/usr/bin/env python3
"""Test the narrow SigLIP MPS workaround: block-0 attention q/k/v projections only."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import types
from pathlib import Path

import requests
import torch
import torch.nn.functional as F
import transformers
from PIL import Image
from transformers import AutoModelForZeroShotImageClassification, AutoProcessor


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compare(a: torch.Tensor, b: torch.Tensor) -> dict:
    x = a.detach().float().cpu().reshape(-1)
    y = b.detach().float().cpu().reshape(-1)
    denom = float(torch.linalg.vector_norm(x).item())
    return {
        "cosine": float(F.cosine_similarity(x.unsqueeze(0), y.unsqueeze(0)).item()),
        "max_abs": float((x - y).abs().max().item()),
        "relative_l2": float(torch.linalg.vector_norm(x - y).item() / denom) if denom else None,
    }


def resolve_block0_qkv(model: torch.nn.Module) -> list[str]:
    names = dict(model.named_modules())
    out: list[str] = []
    for tower in ("vision", "text"):
        base = next((n for n in names if n.endswith(f"{tower}_model.encoder.layers.0")), None)
        if base is None:
            raise RuntimeError(f"no {tower} block 0")
        for kind in ("q_proj", "k_proj", "v_proj"):
            name = base + ".self_attn." + kind
            module = names.get(name)
            if not isinstance(module, torch.nn.Linear):
                raise RuntimeError(f"missing linear {name}")
            out.append(name)
    return out


def patch_named_linears(model: torch.nn.Module, names: list[str]) -> list[str]:
    modules = dict(model.named_modules())
    patched: list[str] = []
    for name in names:
        module = modules[name]
        def matmul_forward(self, input):
            output = torch.matmul(input, self.weight.transpose(-1, -2))
            if self.bias is not None:
                output = output + self.bias
            return output
        module.forward = types.MethodType(matmul_forward, module)
        patched.append(name)
    return patched


def run(model, inputs, device: str):
    model.to(device)
    moved = {k: (v.to(device) if isinstance(v, torch.Tensor) else v) for k, v in inputs.items()}
    model.eval()
    with torch.inference_mode():
        outputs = model(**moved)
    if device == "mps":
        torch.mps.synchronize()
    return (
        outputs.logits_per_image.detach().float().cpu(),
        {
            "model_device": str(next(model.parameters()).device),
            "logits_device": str(outputs.logits_per_image.device),
        },
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    if not torch.backends.mps.is_available():
        raise SystemExit("MPS unavailable")
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") != "0":
        raise SystemExit("fallback must remain disabled")

    cfg = json.loads(Path(a.config).read_text())
    if cfg.get("backend_family") != "siglip":
        raise SystemExit("this discriminator is SigLIP-only")

    response = requests.get(cfg["image_source"], timeout=45)
    response.raise_for_status()
    raw = response.content
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    labels = [str(x["label"]) for x in cfg["concepts"]]
    expected = list(cfg["expected_top_labels"])
    template = cfg.get("parameters", {}).get("prompt_template", "a photo of a {}")
    prompts = [template.format(x) for x in labels]
    processor = AutoProcessor.from_pretrained(cfg["model_id"], revision=cfg.get("model_revision"))
    inputs = processor(
        text=prompts,
        images=image,
        return_tensors="pt",
        padding=cfg.get("parameters", {}).get("text_padding", True),
    )

    cpu_model = AutoModelForZeroShotImageClassification.from_pretrained(
        cfg["model_id"], revision=cfg.get("model_revision")
    )
    cpu_logits, cpu_place = run(cpu_model, inputs, "cpu")
    del cpu_model

    native_model = AutoModelForZeroShotImageClassification.from_pretrained(
        cfg["model_id"], revision=cfg.get("model_revision")
    )
    native_logits, native_place = run(native_model, inputs, "mps")
    del native_model
    torch.mps.empty_cache()

    patched_model = AutoModelForZeroShotImageClassification.from_pretrained(
        cfg["model_id"], revision=cfg.get("model_revision")
    )
    selected = resolve_block0_qkv(patched_model)
    patched_names = patch_named_linears(patched_model, selected)
    patched_logits, patched_place = run(patched_model, inputs, "mps")

    def ranking(logits):
        return [labels[i] for i in torch.argsort(logits[0], descending=True).tolist()]

    cpu_rank = ranking(cpu_logits)
    native_rank = ranking(native_logits)
    patched_rank = ranking(patched_logits)

    receipt = {
        "schema": "visual-concept-siglip-mps-block0-qkv-matmul/v1",
        "model": {
            "family": cfg["backend_family"],
            "id": cfg["model_id"],
            "revision": cfg.get("model_revision"),
        },
        "fixture": {
            "image_sha256": sha256_bytes(raw),
            "labels": labels,
            "expected_top_labels": expected,
        },
        "runtime": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "mps_fallback_env": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"),
        },
        "placements": {
            "cpu": cpu_place,
            "native_mps": native_place,
            "patched_mps": patched_place,
        },
        "treatment": {
            "name": "siglip-block0-qkv-mps-matmul-bias-v0",
            "patched_linear_count": len(patched_names),
            "patched_modules": patched_names,
            "all_other_linears_native": True,
        },
        "rankings": {
            "cpu": cpu_rank,
            "native_mps": native_rank,
            "patched_mps": patched_rank,
        },
        "logit_comparisons": {
            "cpu_vs_native_mps": compare(cpu_logits, native_logits),
            "cpu_vs_patched_mps": compare(cpu_logits, patched_logits),
            "native_vs_patched_mps": compare(native_logits, patched_logits),
        },
        "oracle": {
            "cpu_control_pass": cpu_rank[0] in expected,
            "native_mps_pass": native_rank[0] in expected,
            "patched_mps_pass": patched_rank[0] in expected,
            "workaround_restored_cpu_top1": patched_rank[0] == cpu_rank[0],
            "workaround_restored_full_ranking": patched_rank == cpu_rank,
        },
    }

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "patched_modules": patched_names,
        "rankings": receipt["rankings"],
        "oracle": receipt["oracle"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
