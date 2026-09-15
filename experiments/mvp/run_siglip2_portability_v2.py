#!/usr/bin/env python3
"""Rep 23 retry: non-generative vision/text encoder portability.

This is intentionally a thin modality adapter over the existing Model Spelunker
observe/contrast/validate/provenance method. Model bytes come only from the
already-verified Foundry hydration path supplied via --model-dir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image
import torch
from transformers import AutoModel, AutoProcessor

LOGICAL_ID = "embed/siglip2/base-patch16-224"
UPSTREAM_REPO = "google/siglip2-base-patch16-224"
UPSTREAM_REVISION = "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2"
FOUNDRY_DIGEST = "sha256:c93e953d44105c8cd59be4b893acee43858e9fcb8b4deb20f83535a2165c1c3d"
FOUNDRY_CATALOG_REF = "SemperSupra/model-artifact-foundry@6622753fd5914be87fb1b6d987ceb7cae46c7ff5:catalog/approved.json"

IMAGE_SPECS = [
    {"id": "red", "rgb": [240, 32, 32]},
    {"id": "green", "rgb": [32, 200, 64]},
    {"id": "blue", "rgb": [32, 64, 240]},
    {"id": "red_dim", "rgb": [180, 32, 32]},
]
PRIMARY_TEXTS = ["a solid red image", "a solid green image", "a solid blue image"]
PARAPHRASE_TEXTS = [
    "an image filled with red color",
    "an image filled with green color",
    "an image filled with blue color",
]


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def normalize_rows(x: torch.Tensor) -> torch.Tensor:
    x = x.detach().float().cpu()
    return x / torch.clamp(torch.linalg.vector_norm(x, dim=-1, keepdim=True), min=1e-12)


def cosine_distance(a: torch.Tensor, b: torch.Tensor) -> float:
    a, b = a.detach().float().cpu(), b.detach().float().cpu()
    denom = max(float(torch.linalg.vector_norm(a) * torch.linalg.vector_norm(b)), 1e-12)
    return 1.0 - float(torch.dot(a, b) / denom)


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx, dy = [x - mx for x in xs], [y - my for y in ys]
    den = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    return None if den <= 1e-12 else sum(x*y for x, y in zip(dx, dy)) / den


def derive_text_mask(inputs: Any, processor: Any) -> tuple[torch.Tensor, str]:
    mask = inputs.get("attention_mask")
    if mask is not None:
        return mask.long(), "processor-attention-mask"
    input_ids = inputs["input_ids"]
    tokenizer = getattr(processor, "tokenizer", None)
    pad_id = getattr(tokenizer, "pad_token_id", None)
    if pad_id is None:
        return torch.ones_like(input_ids, dtype=torch.long), "all-ones-no-pad-id"
    return input_ids.ne(int(pad_id)).long(), f"derived-from-pad-token:{int(pad_id)}"


def weighted_pool(hidden: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    m = mask.to(hidden.dtype).unsqueeze(-1)
    return ((hidden * m).sum(dim=1) / torch.clamp(m.sum(dim=1), min=1.0)).detach().float().cpu()


def vision_layer_rows(states: tuple[torch.Tensor, ...]) -> list[dict[str, Any]]:
    rows = []
    for i, h in enumerate(states):
        p = h.detach().float().cpu().mean(dim=1)
        rows.append({
            "layer": i,
            "red_green_cosine_distance": cosine_distance(p[0], p[1]),
            "red_blue_cosine_distance": cosine_distance(p[0], p[2]),
            "red_dim_cosine_distance": cosine_distance(p[0], p[3]),
            "mean_pooled_l2": float(torch.linalg.vector_norm(p, dim=-1).mean()),
        })
    return rows


def text_layer_rows(states: tuple[torch.Tensor, ...], mask: torch.Tensor) -> list[dict[str, Any]]:
    rows = []
    for i, h in enumerate(states):
        p = weighted_pool(h, mask)
        rows.append({
            "layer": i,
            "red_green_cosine_distance": cosine_distance(p[0], p[1]),
            "red_blue_cosine_distance": cosine_distance(p[0], p[2]),
            "red_paraphrase_cosine_distance": cosine_distance(p[0], p[3]),
            "mean_pooled_l2": float(torch.linalg.vector_norm(p, dim=-1).mean()),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=Path("out/siglip2-portability.json"))
    args = ap.parse_args()

    started_wall = time.time()
    started = time.perf_counter()
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    torch.manual_seed(0)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    probe_spec = {
        "images": IMAGE_SPECS,
        "primary_texts": PRIMARY_TEXTS,
        "paraphrase_texts": PARAPHRASE_TEXTS,
        "image_size": [224, 224],
        "generation": "deterministic solid RGB PIL images",
    }
    images = [Image.new("RGB", (224, 224), tuple(x["rgb"])) for x in IMAGE_SPECS]
    texts = PRIMARY_TEXTS + PARAPHRASE_TEXTS

    t = time.perf_counter()
    processor = AutoProcessor.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    model = AutoModel.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    model.eval()
    model_load_seconds = time.perf_counter() - t

    t = time.perf_counter()
    inputs = processor(text=texts, images=images, padding="max_length", return_tensors="pt")
    text_mask, mask_source = derive_text_mask(inputs, processor)
    with torch.inference_mode():
        outputs = model(**inputs, output_hidden_states=True, return_dict=True)

    image_embeds = outputs.image_embeds.detach().float().cpu()
    text_embeds = outputs.text_embeds.detach().float().cpu()
    if tuple(image_embeds.shape) != (4, 768) or tuple(text_embeds.shape) != (6, 768):
        raise RuntimeError(f"unexpected embedding shapes: {tuple(image_embeds.shape)}, {tuple(text_embeds.shape)}")
    if not bool(torch.isfinite(image_embeds).all()) or not bool(torch.isfinite(text_embeds).all()):
        raise RuntimeError("non-finite embedding output")

    inorm, tnorm = normalize_rows(image_embeds), normalize_rows(text_embeds)
    cross = inorm @ tnorm.T
    primary, paraphrase = cross[:3, :3], cross[:3, 3:6]
    image_self, text_self = inorm[:3] @ inorm[:3].T, tnorm[:3] @ tnorm[:3].T

    colors = ["red", "green", "blue"]
    matches, pmargins, qmargins = [], [], []
    ptop, qtop = 0, 0
    for i, color in enumerate(colors):
        pvals, qvals = primary[i], paraphrase[i]
        pw, qw = int(torch.argmax(pvals)), int(torch.argmax(qvals))
        pc, qc = float(pvals[i]), float(qvals[i])
        po = max(float(pvals[j]) for j in range(3) if j != i)
        qo = max(float(qvals[j]) for j in range(3) if j != i)
        pm, qm = pc - po, qc - qo
        pmargins.append(pm); qmargins.append(qm)
        ptop += int(pw == i); qtop += int(qw == i)
        matches.append({
            "image": color,
            "primary_correct_similarity": pc,
            "primary_top1_text": colors[pw],
            "primary_margin": pm,
            "paraphrase_correct_similarity": qc,
            "paraphrase_top1_text": colors[qw],
            "paraphrase_margin": qm,
        })

    vision_hidden = getattr(getattr(outputs, "vision_model_output", None), "hidden_states", None)
    text_hidden = getattr(getattr(outputs, "text_model_output", None), "hidden_states", None)
    if vision_hidden is None:
        with torch.inference_mode():
            vision_hidden = model.vision_model(
                pixel_values=inputs["pixel_values"], output_hidden_states=True, return_dict=True
            ).hidden_states
    if text_hidden is None:
        text_kwargs = {"input_ids": inputs["input_ids"], "output_hidden_states": True, "return_dict": True}
        # Only pass a mask if this text tower accepts one; SigLIP2's processor can
        # legitimately omit it for its fixed-length text representation.
        try:
            with torch.inference_mode():
                text_hidden = model.text_model(attention_mask=text_mask, **text_kwargs).hidden_states
        except TypeError:
            with torch.inference_mode():
                text_hidden = model.text_model(**text_kwargs).hidden_states
    if not vision_hidden or not text_hidden:
        raise RuntimeError("hidden-state instrumentation unavailable")

    vision_layers = vision_layer_rows(tuple(vision_hidden))
    text_layers = text_layer_rows(tuple(text_hidden), text_mask)
    experiment_seconds = time.perf_counter() - t

    pairs = [(0, 1), (0, 2), (1, 2)]
    image_pairs = [float(image_self[i, j]) for i, j in pairs]
    text_pairs = [float(text_self[i, j]) for i, j in pairs]

    observations = {
        "probe_spec": probe_spec,
        "text_mask_source": mask_source,
        "embedding_shapes": {"image": list(image_embeds.shape), "text": list(text_embeds.shape)},
        "primary_cross_modal_cosine": primary.tolist(),
        "paraphrase_cross_modal_cosine": paraphrase.tolist(),
        "image_primary_within_modal_cosine": image_self.tolist(),
        "text_primary_within_modal_cosine": text_self.tolist(),
        "matches": matches,
        "vision_layer_contrasts": vision_layers,
        "text_layer_contrasts": text_layers,
    }
    derived = {
        "primary_top1_rate": ptop / 3.0,
        "paraphrase_top1_rate": qtop / 3.0,
        "primary_mean_margin": sum(pmargins) / 3.0,
        "paraphrase_mean_margin": sum(qmargins) / 3.0,
        "red_image_dim_perturbation_cosine_distance": cosine_distance(image_embeds[0], image_embeds[3]),
        "red_text_paraphrase_cosine_distance": cosine_distance(text_embeds[0], text_embeds[3]),
        "cross_modal_rsa_pairwise_pearson": pearson(image_pairs, text_pairs),
        "portable_instrument_checks": {
            "foundry_oci_identity": True,
            "vision_embedding_observed": True,
            "text_embedding_observed": True,
            "cross_modal_similarity_observed": True,
            "vision_hidden_states_observed": True,
            "text_hidden_states_observed": True,
            "within_modality_geometry_observed": True,
            "deterministic_local_probe_corpus": True,
            "processor_mask_variance_handled": True,
        },
    }
    raw_output_hash = sha256_json({"observations": observations, "derived_metrics": derived})
    hydrate_seconds = float(os.environ.get("FOUNDRY_HYDRATE_SECONDS", "0") or 0.0)
    total_seconds = time.perf_counter() - started
    git_sha = os.environ.get("GITHUB_SHA")
    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(started_wall)}")

    bundle = {
        "probe_id": "multimodal-portability-siglip2-v1",
        "instrument": "multimodal-embedding-geometry-and-layer-contrast-suite",
        "instrument_version": "mvp-2",
        "model_identity": {
            "repository": UPSTREAM_REPO,
            "revision": UPSTREAM_REVISION,
            "logical_id": LOGICAL_ID,
            "model_class": "vision-text-embedding-encoder",
        },
        "artifact_provenance": {
            "tracked": True,
            "foundry_repository": "SemperSupra/model-artifact-foundry",
            "logical_artifact_id": LOGICAL_ID,
            "upstream_provider": "huggingface",
            "upstream_repository": UPSTREAM_REPO,
            "upstream_revision": UPSTREAM_REVISION,
            "identity_kind": "oci",
            "identity_digest": FOUNDRY_DIGEST,
            "foundry_record_ref": FOUNDRY_CATALOG_REF,
            "consumer_selection_ref": f"model-spelunker@{git_sha}" if git_sha else None,
            "verified": True,
            "verification_ref": "digest-pinned Foundry hydrate with bundle/file verification",
            "tokenizer_artifact": None,
        },
        "access_tier": "A2",
        "evidence_level": "REPRODUCED",
        "claim_tags": ["MULTIMODAL", "EMBEDDING_GEOMETRY"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {
            "scope": "instrument portability on a tiny synthetic corpus; not a model quality benchmark",
            "synthetic_probe_count": 4,
            "text_probe_count": 6,
        },
        "known_assumptions": [
            "solid-color synthetic images are sufficient to exercise both towers and cross-modal similarity",
            "mean-pooled hidden-state contrasts are descriptive observability measures, not localized mechanisms",
        ],
        "known_failure_modes": [
            "synthetic color probes may be out of distribution and must not be generalized to natural-image quality",
            "three-item RSA is descriptive and statistically weak",
        ],
        "cost": {
            "foundry_hydrate_seconds": hydrate_seconds,
            "model_load_seconds": model_load_seconds,
            "experiment_seconds": experiment_seconds,
            "total_script_seconds": total_seconds,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        },
        "provenance": {
            "run_id": str(run_id),
            "code_revision": git_sha,
            "model_revision": UPSTREAM_REVISION,
            "tokenizer_revision": UPSTREAM_REVISION,
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "torch": torch.__version__,
                "transformers": __import__("transformers").__version__,
                "pillow": __import__("PIL").__version__,
                "torch_num_threads": torch.get_num_threads(),
            },
            "randomness": {"torch_manual_seed": 0, "sampling": False},
            "raw_input_hash": sha256_json(probe_spec),
            "raw_output_hash": raw_output_hash,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "probe_id": bundle["probe_id"],
        "output": str(args.output),
        "mask_source": mask_source,
        "primary_top1_rate": derived["primary_top1_rate"],
        "paraphrase_top1_rate": derived["paraphrase_top1_rate"],
        "rsa": derived["cross_modal_rsa_pairwise_pearson"],
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
        "total_seconds": total_seconds,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
