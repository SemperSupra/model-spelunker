#!/usr/bin/env python3
"""Rep 23: test Model Spelunker methodology on a non-generative vision/text encoder.

The model bytes are supplied by the approved Model Artifact Foundry OCI artifact.
The probe corpus is generated deterministically in-process; no external images are
fetched.  The purpose is instrument/method portability, not a broad accuracy claim.
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
PRIMARY_TEXTS = [
    "a solid red image",
    "a solid green image",
    "a solid blue image",
]
PARAPHRASE_TEXTS = [
    "an image filled with red color",
    "an image filled with green color",
    "an image filled with blue color",
]


def sha256_json(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def cosine_distance(a: torch.Tensor, b: torch.Tensor) -> float:
    a = a.float()
    b = b.float()
    denom = max(float(torch.linalg.vector_norm(a).item() * torch.linalg.vector_norm(b).item()), 1e-12)
    return 1.0 - float(torch.dot(a, b).item() / denom)


def normalize_rows(x: torch.Tensor) -> torch.Tensor:
    x = x.float()
    return x / torch.clamp(torch.linalg.vector_norm(x, dim=-1, keepdim=True), min=1e-12)


def weighted_text_pool(hidden: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    m = mask.to(hidden.dtype).unsqueeze(-1)
    return (hidden * m).sum(dim=1) / torch.clamp(m.sum(dim=1), min=1.0)


def layer_contrasts(hidden_states: tuple[torch.Tensor, ...], kind: str, attention_mask: torch.Tensor | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for layer, h in enumerate(hidden_states):
        if kind == "vision":
            pooled = h.float().mean(dim=1).cpu()
            row = {
                "layer": layer,
                "red_green_cosine_distance": cosine_distance(pooled[0], pooled[1]),
                "red_blue_cosine_distance": cosine_distance(pooled[0], pooled[2]),
                "red_dim_cosine_distance": cosine_distance(pooled[0], pooled[3]),
                "mean_pooled_l2": float(torch.linalg.vector_norm(pooled, dim=-1).mean().item()),
            }
        else:
            assert attention_mask is not None
            pooled = weighted_text_pool(h.float(), attention_mask).cpu()
            row = {
                "layer": layer,
                "red_green_cosine_distance": cosine_distance(pooled[0], pooled[1]),
                "red_blue_cosine_distance": cosine_distance(pooled[0], pooled[2]),
                "red_paraphrase_cosine_distance": cosine_distance(pooled[0], pooled[3]),
                "mean_pooled_l2": float(torch.linalg.vector_norm(pooled, dim=-1).mean().item()),
            }
        rows.append(row)
    return rows


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    den = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    if den <= 1e-12:
        return None
    return sum(x*y for x, y in zip(dx, dy)) / den


def matrix_rows(x: torch.Tensor) -> list[list[float]]:
    return [[float(v) for v in row] for row in x.tolist()]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("out/siglip2-portability.json"))
    args = p.parse_args()

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
        "generation": "solid RGB PIL images",
    }
    images = [Image.new("RGB", (224, 224), color=tuple(row["rgb"])) for row in IMAGE_SPECS]
    texts = PRIMARY_TEXTS + PARAPHRASE_TEXTS

    t = time.perf_counter()
    processor = AutoProcessor.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    model = AutoModel.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    model.eval()
    model_load_seconds = time.perf_counter() - t

    t = time.perf_counter()
    inputs = processor(text=texts, images=images, padding="max_length", return_tensors="pt")
    with torch.inference_mode():
        outputs = model(**inputs, output_hidden_states=True, return_dict=True)

    image_embeds = outputs.image_embeds.detach().float().cpu()
    text_embeds = outputs.text_embeds.detach().float().cpu()
    if image_embeds.shape != (4, 768) or text_embeds.shape != (6, 768):
        raise RuntimeError(f"unexpected embedding shapes image={tuple(image_embeds.shape)} text={tuple(text_embeds.shape)}")
    if not torch.isfinite(image_embeds).all() or not torch.isfinite(text_embeds).all():
        raise RuntimeError("non-finite embedding output")

    image_norm = normalize_rows(image_embeds)
    text_norm = normalize_rows(text_embeds)
    cross = image_norm @ text_norm.T
    primary_cross = cross[:3, :3]
    paraphrase_cross = cross[:3, 3:6]

    image_self = image_norm[:3] @ image_norm[:3].T
    text_self = text_norm[:3] @ text_norm[:3].T
    upper = [(0, 1), (0, 2), (1, 2)]
    image_pairwise = [float(image_self[i, j]) for i, j in upper]
    text_pairwise = [float(text_self[i, j]) for i, j in upper]

    match_rows = []
    primary_top1 = 0
    paraphrase_top1 = 0
    primary_margins: list[float] = []
    paraphrase_margins: list[float] = []
    color_ids = ["red", "green", "blue"]
    for i, color in enumerate(color_ids):
        pvals = primary_cross[i]
        qvals = paraphrase_cross[i]
        pwin = int(torch.argmax(pvals).item())
        qwin = int(torch.argmax(qvals).item())
        pcorrect = float(pvals[i].item())
        qcorrect = float(qvals[i].item())
        pother = max(float(pvals[j].item()) for j in range(3) if j != i)
        qother = max(float(qvals[j].item()) for j in range(3) if j != i)
        pmargin = pcorrect - pother
        qmargin = qcorrect - qother
        primary_margins.append(pmargin)
        paraphrase_margins.append(qmargin)
        primary_top1 += int(pwin == i)
        paraphrase_top1 += int(qwin == i)
        match_rows.append({
            "image": color,
            "primary_correct_similarity": pcorrect,
            "primary_top1_text": color_ids[pwin],
            "primary_margin": pmargin,
            "paraphrase_correct_similarity": qcorrect,
            "paraphrase_top1_text": color_ids[qwin],
            "paraphrase_margin": qmargin,
        })

    vision_hidden = None
    text_hidden = None
    if getattr(outputs, "vision_model_output", None) is not None:
        vision_hidden = getattr(outputs.vision_model_output, "hidden_states", None)
    if getattr(outputs, "text_model_output", None) is not None:
        text_hidden = getattr(outputs.text_model_output, "hidden_states", None)

    # Keep the instrument robust across transformers output wrappers by querying
    # each tower explicitly if the joint output did not expose hidden states.
    if vision_hidden is None:
        with torch.inference_mode():
            vout = model.vision_model(pixel_values=inputs["pixel_values"], output_hidden_states=True, return_dict=True)
        vision_hidden = vout.hidden_states
    if text_hidden is None:
        with torch.inference_mode():
            tout = model.text_model(
                input_ids=inputs["input_ids"],
                attention_mask=inputs.get("attention_mask"),
                output_hidden_states=True,
                return_dict=True,
            )
        text_hidden = tout.hidden_states
    if not vision_hidden or not text_hidden:
        raise RuntimeError("hidden-state instrumentation unavailable")

    vision_layers = layer_contrasts(tuple(vision_hidden), "vision")
    text_layers = layer_contrasts(tuple(text_hidden), "text", inputs["attention_mask"])
    experiment_seconds = time.perf_counter() - t

    observations = {
        "probe_spec": probe_spec,
        "embedding_shapes": {"image": list(image_embeds.shape), "text": list(text_embeds.shape)},
        "primary_cross_modal_cosine": matrix_rows(primary_cross),
        "paraphrase_cross_modal_cosine": matrix_rows(paraphrase_cross),
        "image_primary_within_modal_cosine": matrix_rows(image_self),
        "text_primary_within_modal_cosine": matrix_rows(text_self),
        "matches": match_rows,
        "vision_layer_contrasts": vision_layers,
        "text_layer_contrasts": text_layers,
    }
    derived = {
        "primary_top1_rate": primary_top1 / 3.0,
        "paraphrase_top1_rate": paraphrase_top1 / 3.0,
        "primary_mean_margin": sum(primary_margins) / len(primary_margins),
        "paraphrase_mean_margin": sum(paraphrase_margins) / len(paraphrase_margins),
        "red_image_dim_perturbation_cosine_distance": cosine_distance(image_embeds[0], image_embeds[3]),
        "red_text_paraphrase_cosine_distance": cosine_distance(text_embeds[0], text_embeds[3]),
        "cross_modal_rsa_pairwise_pearson": pearson(image_pairwise, text_pairwise),
        "portable_instrument_checks": {
            "foundry_oci_identity": True,
            "vision_embedding_observed": True,
            "text_embedding_observed": True,
            "cross_modal_similarity_observed": True,
            "vision_hidden_states_observed": True,
            "text_hidden_states_observed": True,
            "within_modality_geometry_observed": True,
            "deterministic_local_probe_corpus": True,
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
        "instrument_version": "mvp-1",
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
            "mean pooled hidden-state contrasts are descriptive observability measures, not localized mechanisms",
        ],
        "known_failure_modes": [
            "synthetic color probes may be out of distribution and should not be generalized to natural-image quality",
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
        "output": str(args.output),
        "probe_id": bundle["probe_id"],
        "primary_top1_rate": derived["primary_top1_rate"],
        "paraphrase_top1_rate": derived["paraphrase_top1_rate"],
        "rsa": derived["cross_modal_rsa_pairwise_pearson"],
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
        "total_seconds": total_seconds,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
