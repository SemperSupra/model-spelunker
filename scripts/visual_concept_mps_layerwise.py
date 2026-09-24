#!/usr/bin/env python3
"""Layerwise CPU-vs-MPS localization for the frozen Visual Concept Worker workload."""
from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any

import requests
import torch
import torch.nn.functional as F
import transformers
from PIL import Image
from transformers import AutoModelForZeroShotImageClassification, AutoProcessor


LAYER_RE = re.compile(r"^(?P<prefix>.*(?:vision_model|text_model)\.encoder\.layers\.)(?P<index>[0-9]+)$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _first_tensor(value: Any) -> torch.Tensor | None:
    if isinstance(value, torch.Tensor):
        return value
    if isinstance(value, (tuple, list)):
        for item in value:
            found = _first_tensor(item)
            if found is not None:
                return found
    if hasattr(value, "to_tuple"):
        try:
            return _first_tensor(value.to_tuple())
        except Exception:
            return None
    return None


def tensor_metrics(cpu: torch.Tensor, other: torch.Tensor) -> dict[str, Any]:
    a = cpu.detach().float().cpu()
    b = other.detach().float().cpu()
    if a.shape != b.shape:
        return {
            "shape_match": False,
            "cpu_shape": list(a.shape),
            "mps_shape": list(b.shape),
        }
    af = a.reshape(-1)
    bf = b.reshape(-1)
    if not af.numel():
        return {
            "shape_match": True,
            "shape": list(a.shape),
            "cosine": None,
            "max_abs": 0.0,
            "mean_abs": 0.0,
            "relative_l2": None,
            "cpu_finite": True,
            "mps_finite": True,
        }
    cpu_finite = bool(torch.isfinite(af).all().item())
    mps_finite = bool(torch.isfinite(bf).all().item())
    denom = float(torch.linalg.vector_norm(af).item())
    cosine = float(F.cosine_similarity(af.unsqueeze(0), bf.unsqueeze(0)).item())
    return {
        "shape_match": True,
        "shape": list(a.shape),
        "cosine": cosine,
        "max_abs": float((a - b).abs().max().item()),
        "mean_abs": float((a - b).abs().mean().item()),
        "relative_l2": float(torch.linalg.vector_norm(af - bf).item() / denom) if denom else None,
        "cpu_finite": cpu_finite,
        "mps_finite": mps_finite,
    }


def _tower_layers(names: list[str], tower: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    needle = f"{tower}_model.encoder.layers."
    for name in names:
        if needle not in name:
            continue
        match = LAYER_RE.fullmatch(name)
        if match:
            out.append((int(match.group("index")), name))
    return sorted(set(out))


def _pick_layer_names(layers: list[tuple[int, str]]) -> list[str]:
    if not layers:
        return []
    indexes = [0, len(layers) // 2, len(layers) - 1]
    return [layers[i][1] for i in sorted(set(indexes))]


def select_probe_names(model: torch.nn.Module) -> dict[str, list[str]]:
    names = [name for name, _ in model.named_modules()]
    selected: dict[str, list[str]] = {"vision": [], "text": []}

    for tower in ("vision", "text"):
        embedding_suffix = f"{tower}_model.embeddings"
        embedding = next((name for name in names if name.endswith(embedding_suffix)), None)
        if embedding:
            selected[tower].append(embedding)

        selected[tower].extend(_pick_layer_names(_tower_layers(names, tower)))

        suffixes = (
            f"{tower}_model.pre_layrnorm",
            f"{tower}_model.post_layernorm",
            f"{tower}_model.final_layer_norm",
        )
        for suffix in suffixes:
            name = next((candidate for candidate in names if candidate.endswith(suffix)), None)
            if name and name not in selected[tower]:
                selected[tower].append(name)

    projection_candidates = {
        "vision": ("visual_projection", "vision_projection"),
        "text": ("text_projection",),
    }
    for tower, suffixes in projection_candidates.items():
        for suffix in suffixes:
            name = next((candidate for candidate in names if candidate.endswith(suffix)), None)
            if name and name not in selected[tower]:
                selected[tower].append(name)

    if not selected["vision"] or not selected["text"]:
        raise RuntimeError(f"could not identify both model towers: {selected}")
    return selected


def run_model(
    model_id: str,
    revision: str | None,
    inputs_cpu: dict[str, Any],
    device: str,
    expected_probes: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    model = AutoModelForZeroShotImageClassification.from_pretrained(model_id, revision=revision)
    probes = select_probe_names(model)
    if expected_probes is not None and probes != expected_probes:
        raise RuntimeError(f"probe topology changed between device realizations: {probes!r} != {expected_probes!r}")

    captures: dict[str, torch.Tensor] = {}
    handles = []

    module_map = dict(model.named_modules())
    for name in probes["vision"] + probes["text"]:
        module = module_map[name]

        def capture(_module, _inputs, output, *, probe_name=name):
            tensor = _first_tensor(output)
            if tensor is None:
                raise RuntimeError(f"probe {probe_name} produced no tensor")
            captures[probe_name] = tensor.detach().float().cpu()

        handles.append(module.register_forward_hook(capture))

    model.to(device)
    model.eval()
    inputs = {
        key: value.to(device) if isinstance(value, torch.Tensor) else value
        for key, value in inputs_cpu.items()
    }

    with torch.inference_mode():
        outputs = model(**inputs)

    logits = outputs.logits_per_image.detach().float().cpu()
    for handle in handles:
        handle.remove()

    missing = [name for name in probes["vision"] + probes["text"] if name not in captures]
    if missing:
        raise RuntimeError(f"missing probe outputs: {missing}")

    placement = {
        "requested_device": device,
        "model_device": str(next(model.parameters()).device),
        "logits_device": str(outputs.logits_per_image.device),
    }

    del outputs, inputs, model
    gc.collect()
    if device == "mps":
        torch.mps.synchronize()
        torch.mps.empty_cache()

    return {
        "probes": probes,
        "captures": captures,
        "logits": logits,
        "placement": placement,
    }


def _stage_order(probes: dict[str, list[str]], tower: str) -> list[str]:
    return list(probes[tower])


def _first_material_divergence(stages: list[dict[str, Any]]) -> dict[str, Any] | None:
    # Diagnostic heuristic only; it does not define semantic correctness.
    for stage in stages:
        metrics = stage["metrics"]
        cosine = metrics.get("cosine")
        rel = metrics.get("relative_l2")
        if metrics.get("shape_match") is not True:
            return {"name": stage["name"], "reason": "shape_mismatch"}
        if metrics.get("cpu_finite") is not True or metrics.get("mps_finite") is not True:
            return {"name": stage["name"], "reason": "nonfinite"}
        if (cosine is not None and cosine < 0.999) or (rel is not None and rel > 0.01):
            return {
                "name": stage["name"],
                "reason": "diagnostic_threshold",
                "cosine": cosine,
                "relative_l2": rel,
            }
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
        raise SystemExit("MPS unavailable")
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") != "0":
        raise SystemExit("diagnostic requires PYTORCH_ENABLE_MPS_FALLBACK=0")

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    response = requests.get(cfg["image_source"], timeout=45)
    response.raise_for_status()
    raw = response.content
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    labels = [str(x["label"]) for x in cfg["concepts"]]
    template = cfg.get("parameters", {}).get("prompt_template", "a photo of a {}")
    prompts = [template.format(label) for label in labels]
    padding = cfg.get("parameters", {}).get("text_padding", True)

    processor = AutoProcessor.from_pretrained(cfg["model_id"], revision=cfg.get("model_revision"))
    inputs = processor(text=prompts, images=image, return_tensors="pt", padding=padding)

    cpu = run_model(cfg["model_id"], cfg.get("model_revision"), inputs, "cpu")
    mps = run_model(
        cfg["model_id"],
        cfg.get("model_revision"),
        inputs,
        "mps",
        expected_probes=cpu["probes"],
    )

    towers: dict[str, Any] = {}
    for tower in ("vision", "text"):
        stages = []
        for name in _stage_order(cpu["probes"], tower):
            stages.append({
                "name": name,
                "metrics": tensor_metrics(cpu["captures"][name], mps["captures"][name]),
            })
        towers[tower] = {
            "stages": stages,
            "first_material_divergence": _first_material_divergence(stages),
        }

    cpu_logits = cpu["logits"][0]
    mps_logits = mps["logits"][0]
    receipt = {
        "schema": "visual-concept-mps-layerwise/v1",
        "model": {
            "family": cfg["backend_family"],
            "id": cfg["model_id"],
            "revision": cfg.get("model_revision"),
        },
        "fixture": {
            "image_sha256": sha256_bytes(raw),
            "labels": labels,
            "prompts": prompts,
        },
        "runtime": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "mps_built": torch.backends.mps.is_built(),
            "mps_available": torch.backends.mps.is_available(),
            "mps_fallback_env": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"),
        },
        "placement": {"cpu": cpu["placement"], "mps": mps["placement"]},
        "rankings": {
            "cpu": [labels[i] for i in torch.argsort(cpu_logits, descending=True).tolist()],
            "mps": [labels[i] for i in torch.argsort(mps_logits, descending=True).tolist()],
        },
        "logits": tensor_metrics(cpu["logits"], mps["logits"]),
        "towers": towers,
        "diagnostic_threshold": {
            "cosine_lt": 0.999,
            "relative_l2_gt": 0.01,
            "meaning": "localization heuristic only; not semantic acceptance",
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("VISUAL_MPS_LAYERWISE=" + str(out))
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
