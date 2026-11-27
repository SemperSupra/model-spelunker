#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

import torch
import transformers
from huggingface_hub import snapshot_download
from PIL import Image
from transformers import AutoModel, AutoProcessor

LABELS = ["animals", "humans", "landscape"]
VISION_LAYER_RE = re.compile(r"(?:^|\.)(?:vision_model\.)?encoder\.layers\.(\d+)$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tensor_sha256(tensor: torch.Tensor) -> str:
    value = tensor.detach().cpu().contiguous()
    h = hashlib.sha256()
    header = json.dumps(
        {"shape": list(value.shape), "dtype": str(value.dtype)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    h.update(header)
    h.update(b"\0")
    h.update(value.numpy().tobytes(order="C"))
    return h.hexdigest()


def first_tensor(value: Any) -> torch.Tensor | None:
    if torch.is_tensor(value):
        return value
    if isinstance(value, (tuple, list)):
        for item in value:
            found = first_tensor(item)
            if found is not None:
                return found
    for attr in ("last_hidden_state", "pooler_output", "hidden_states"):
        if hasattr(value, attr):
            found = first_tensor(getattr(value, attr))
            if found is not None:
                return found
    return None


def summarize_tensor(tensor: torch.Tensor) -> dict[str, Any]:
    x = tensor.detach().float().cpu()
    flat = x.reshape(-1)
    # Bound the statistical work while preserving deterministic coverage.
    if flat.numel() > 1_000_000:
        step = math.ceil(flat.numel() / 1_000_000)
        flat = flat[::step]
    finite = torch.isfinite(flat)
    if not finite.all().item():
        raise RuntimeError("activation summary encountered non-finite values")
    return {
        "shape": list(tensor.shape),
        "dtype": str(tensor.dtype),
        "sampled_elements": int(flat.numel()),
        "mean": float(flat.mean().item()),
        "std": float(flat.std(unbiased=False).item()),
        "rms": float(torch.sqrt(torch.mean(flat * flat)).item()),
        "min": float(flat.min().item()),
        "max": float(flat.max().item()),
        "near_zero_fraction": float((flat.abs() < 1e-6).float().mean().item()),
    }


def select_vision_layers(model: torch.nn.Module) -> list[tuple[str, torch.nn.Module]]:
    matched: list[tuple[int, str, torch.nn.Module]] = []
    for name, module in model.named_modules():
        if "vision" not in name:
            continue
        match = VISION_LAYER_RE.search(name)
        if match:
            matched.append((int(match.group(1)), name, module))
    if not matched:
        raise RuntimeError("no vision encoder layers discovered for bounded activation observation")
    matched.sort(key=lambda item: item[0])
    first = matched[0]
    last = matched[-1]
    selected = [first]
    if last[0] != first[0]:
        selected.append(last)
    return [(name, module) for _, name, module in selected]


def load_study(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_model_snapshot(study: dict[str, Any], cache_root: Path) -> tuple[Path, list[dict[str, Any]]]:
    model = study["model"]
    expected_files = model["files"]
    local_dir = Path(
        snapshot_download(
            repo_id=model["upstream_repository"],
            revision=model["upstream_revision"],
            allow_patterns=[entry["path"] for entry in expected_files],
            cache_dir=str(cache_root),
        )
    )
    receipts: list[dict[str, Any]] = []
    for entry in expected_files:
        path = local_dir / entry["path"]
        if not path.is_file():
            raise RuntimeError(f"missing declared model file: {entry['path']}")
        actual_sha = sha256_file(path)
        actual_size = path.stat().st_size
        if actual_sha != entry["sha256"]:
            raise RuntimeError(
                f"model file hash mismatch for {entry['path']}: {actual_sha} != {entry['sha256']}"
            )
        if "size_bytes" in entry and actual_size != entry["size_bytes"]:
            raise RuntimeError(
                f"model file size mismatch for {entry['path']}: {actual_size} != {entry['size_bytes']}"
            )
        receipts.append({
            "path": entry["path"],
            "sha256": actual_sha,
            "size_bytes": actual_size,
        })
    return local_dir, receipts


def acquire_stimulus(study: dict[str, Any], work_dir: Path) -> tuple[Path, dict[str, Any]]:
    stimulus = study["stimuli"][0]
    path = work_dir / "stimulus.png"
    request = urllib.request.Request(stimulus["source"], headers={"User-Agent": "model-spelunker/rep1"})
    with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as out:
        out.write(response.read())
    actual_sha = sha256_file(path)
    expected = stimulus.get("expected_sha256")
    if expected is not None and actual_sha != expected:
        raise RuntimeError(f"stimulus hash mismatch: {actual_sha} != {expected}")
    with Image.open(path) as image:
        width, height = image.size
        mode = image.mode
    return path, {
        "stimulus_id": stimulus["stimulus_id"],
        "source": stimulus["source"],
        "acquired_sha256": actual_sha,
        "expected_sha256": expected,
        "width": width,
        "height": height,
        "mode": mode,
    }


def run(study_path: Path, output_path: Path) -> int:
    study = load_study(study_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = output_path.parent / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "schema_version": 1,
        "study_id": study["study_id"],
        "evidence_class": study["evidence_class"],
        "disclosure_mode": study["disclosure_mode"],
        "execution_disposition": "EXECUTED_FAILED",
        "scientific_disposition": "INCONCLUSIVE",
        "study_declaration_sha256": sha256_file(study_path),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
        },
        "model": {
            "logical_id": study["model"]["logical_id"],
            "foundry_digest": study["model"].get("foundry_digest"),
            "foundry_evidence": study["model"].get("foundry_evidence"),
            "upstream_repository": study["model"]["upstream_repository"],
            "upstream_revision": study["model"]["upstream_revision"],
        },
    }

    try:
        model_dir, model_receipts = verify_model_snapshot(study, work_dir / "hf-cache")
        result["model"]["files"] = model_receipts
        stimulus_path, stimulus_receipt = acquire_stimulus(study, work_dir)
        result["stimulus"] = stimulus_receipt

        processor = AutoProcessor.from_pretrained(
            str(model_dir), local_files_only=True, trust_remote_code=False
        )
        model = AutoModel.from_pretrained(
            str(model_dir), local_files_only=True, trust_remote_code=False, use_safetensors=True
        )
        model.eval()

        activation_summaries: dict[str, dict[str, Any]] = {}
        handles = []
        for name, module in select_vision_layers(model):
            def hook(_module: torch.nn.Module, _inputs: tuple[Any, ...], output: Any, *, layer_name: str = name) -> None:
                tensor = first_tensor(output)
                if tensor is None:
                    raise RuntimeError(f"no tensor found in activation output for {layer_name}")
                activation_summaries[layer_name] = summarize_tensor(tensor)
            handles.append(module.register_forward_hook(hook))

        with Image.open(stimulus_path).convert("RGB") as image:
            inputs = processor(
                text=LABELS,
                images=image,
                padding="max_length",
                return_tensors="pt",
            )
        pixel_values = inputs.get("pixel_values")
        if pixel_values is None:
            raise RuntimeError("processor did not produce pixel_values")
        result["realization"] = {
            "pixel_values_sha256": tensor_sha256(pixel_values),
            "pixel_values_shape": list(pixel_values.shape),
            "pixel_values_dtype": str(pixel_values.dtype),
            "labels": LABELS,
        }

        with torch.no_grad():
            outputs = model(**inputs)
        for handle in handles:
            handle.remove()

        logits = outputs.logits_per_image.detach().float().cpu()
        if not torch.isfinite(logits).all().item():
            raise RuntimeError("model produced non-finite image/text logits")
        scores = torch.sigmoid(logits)[0]
        ranking = sorted(
            ({"label": label, "score": float(score)} for label, score in zip(LABELS, scores.tolist())),
            key=lambda item: item["score"],
            reverse=True,
        )
        result["behavior"] = {
            "logits_per_image": [float(value) for value in logits[0].tolist()],
            "sigmoid_scores": ranking,
            "top_label": ranking[0]["label"],
        }
        result["activation_summaries"] = activation_summaries
        if not activation_summaries:
            raise RuntimeError("no activation summaries were recorded")

        result["execution_disposition"] = "EXECUTED_PASSED"
        result["scientific_disposition"] = (
            "SUPPORTED_WITHIN_TOLERANCE" if ranking[0]["label"] == "animals" else "NOT_SUPPORTED"
        )
        result["scientific_scope"] = "public model-card engineering example only"
        output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except Exception as exc:
        result["execution_error"] = f"{type(exc).__name__}: {exc}"
        output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    study = Path(os.environ.get("STUDY_JSON", Path(__file__).with_name("study.json")))
    output = Path(os.environ.get("RESULT_JSON", "result.json"))
    raise SystemExit(run(study, output))
