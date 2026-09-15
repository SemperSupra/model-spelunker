#!/usr/bin/env python3
"""Rep 15: attention/information-flow localization for the user-start protocol effect.

Read attention and residual states without intervention. Compare start-token-present
and start-token-absent prompts using token-aligned user-content and answer-boundary
regions. The goal is to identify layers/heads/routes worth causal patching next.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import time
from pathlib import Path
from typing import Any

import torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer

import run_activation_poke as poke
import run_aligned_activation_patch as aligned
import run_rep as base


def now() -> float:
    return time.perf_counter()


def cosine_distance(a: torch.Tensor, b: torch.Tensor) -> float:
    denom = max(float(torch.linalg.vector_norm(a).item() * torch.linalg.vector_norm(b).item()), 1e-12)
    return 1.0 - float(torch.dot(a, b).item() / denom)


def compact_surface(surface: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in surface.items() if k != "final_hidden"}


def prompt_forward(model: Any, tokenizer: Any, prompt: str):
    encoded = tokenizer(prompt, return_tensors="pt")
    with torch.inference_mode():
        out = model(
            **encoded,
            output_hidden_states=True,
            output_attentions=True,
            use_cache=False,
        )
    if out.attentions is None:
        raise RuntimeError("model did not return attentions; eager attention instrumentation required")
    return encoded, out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/attention-flow.json"))
    args = parser.parse_args()

    started_wall, started = time.time(), now()
    timings: dict[str, float] = {}
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    torch.manual_seed(0)

    t = now()
    model_dir = Path(snapshot_download(
        repo_id=base.MODEL_REPO,
        revision=base.MODEL_REVISION,
        allow_patterns=base.MODEL_FILES,
        local_dir="/tmp/model-spelunker-smollm2",
    )).resolve()
    timings["hydrate_seconds"] = now() - t

    t = now()
    manifest_digest, files = base.content_manifest(model_dir)
    timings["artifact_verify_seconds"] = now() - t

    t = now()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir,
        local_files_only=True,
        torch_dtype=torch.float32,
        attn_implementation="eager",
    )
    model.eval()
    timings["model_load_seconds"] = now() - t

    observations: list[dict[str, Any]] = []
    aggregate: dict[tuple[int, int], list[dict[str, float]]] = {}
    layer_region_hidden: dict[int, list[dict[str, float]]] = {}
    t = now()

    for task in poke.HELDOUT:
        no_prompt = poke.render(task["user"], False)
        start_prompt = poke.render(task["user"], True)
        regions = aligned.aligned_regions(tokenizer, task["user"], no_prompt, start_prompt)
        no_regions = {
            name: [a for a, _ in pairs]
            for name, pairs in regions.items()
        }
        start_regions = {
            name: [b for _, b in pairs]
            for name, pairs in regions.items()
        }

        no_encoded, no_out = prompt_forward(model, tokenizer, no_prompt)
        start_encoded, start_out = prompt_forward(model, tokenizer, start_prompt)
        if len(no_out.attentions) != len(start_out.attentions):
            raise RuntimeError("attention layer count mismatch")

        baseline = poke.condition_surface(model, tokenizer, no_prompt, task["candidates"], task["correct"])
        target = poke.condition_surface(model, tokenizer, start_prompt, task["candidates"], task["correct"])
        base_surface_distance = poke.centered_distance(baseline["score_vector"], target["score_vector"])

        layer_rows = []
        for layer, (no_attn_t, start_attn_t) in enumerate(zip(no_out.attentions, start_out.attentions)):
            no_attn = no_attn_t[0].detach().float().cpu()
            start_attn = start_attn_t[0].detach().float().cpu()
            if no_attn.shape[0] != start_attn.shape[0]:
                raise RuntimeError("attention head count mismatch")
            no_q = no_attn.shape[1] - 1
            start_q = start_attn.shape[1] - 1

            # Post-layer residual regional representations.
            no_hidden = no_out.hidden_states[layer + 1][0].detach().float().cpu()
            start_hidden = start_out.hidden_states[layer + 1][0].detach().float().cpu()
            no_user = no_hidden[no_regions["user-content"], :].mean(dim=0)
            start_user = start_hidden[start_regions["user-content"], :].mean(dim=0)
            no_boundary = no_hidden[no_regions["answer-boundary"], :].mean(dim=0)
            start_boundary = start_hidden[start_regions["answer-boundary"], :].mean(dim=0)
            user_hidden_distance = cosine_distance(no_user, start_user)
            boundary_hidden_distance = cosine_distance(no_boundary, start_boundary)
            layer_region_hidden.setdefault(layer, []).append({
                "user_hidden_cosine_distance": user_hidden_distance,
                "boundary_hidden_cosine_distance": boundary_hidden_distance,
            })

            head_rows = []
            aligned_pairs = regions["all-aligned"]
            no_aligned = [a for a, _ in aligned_pairs]
            start_aligned = [b for _, b in aligned_pairs]
            for head in range(no_attn.shape[0]):
                no_user_mass = float(no_attn[head, no_q, no_regions["user-content"]].sum().item())
                start_user_mass = float(start_attn[head, start_q, start_regions["user-content"]].sum().item())
                no_boundary_mass = float(no_attn[head, no_q, no_regions["answer-boundary"]].sum().item())
                start_boundary_mass = float(start_attn[head, start_q, start_regions["answer-boundary"]].sum().item())

                no_vec = no_attn[head, no_q, no_aligned]
                start_vec = start_attn[head, start_q, start_aligned]
                raw_l1 = float(torch.abs(start_vec - no_vec).sum().item())
                no_norm = no_vec / torch.clamp(no_vec.sum(), min=1e-12)
                start_norm = start_vec / torch.clamp(start_vec.sum(), min=1e-12)
                aligned_tv = float(0.5 * torch.abs(start_norm - no_norm).sum().item())

                row = {
                    "head": head,
                    "no_user_mass": no_user_mass,
                    "start_user_mass": start_user_mass,
                    "user_mass_delta": start_user_mass - no_user_mass,
                    "no_boundary_mass": no_boundary_mass,
                    "start_boundary_mass": start_boundary_mass,
                    "boundary_mass_delta": start_boundary_mass - no_boundary_mass,
                    "aligned_raw_l1": raw_l1,
                    "aligned_normalized_tv": aligned_tv,
                }
                head_rows.append(row)
                aggregate.setdefault((layer, head), []).append({
                    "user_mass_delta": row["user_mass_delta"],
                    "boundary_mass_delta": row["boundary_mass_delta"],
                    "aligned_raw_l1": raw_l1,
                    "aligned_normalized_tv": aligned_tv,
                })

            layer_rows.append({
                "layer": layer,
                "user_hidden_cosine_distance": user_hidden_distance,
                "boundary_hidden_cosine_distance": boundary_hidden_distance,
                "heads": head_rows,
            })

        observations.append({
            "task_id": task["task_id"],
            "user_sha256": "sha256:" + hashlib.sha256(task["user"].encode("utf-8")).hexdigest(),
            "correct": task["correct"],
            "region_token_counts": {
                "user-content": len(regions["user-content"]),
                "answer-boundary": len(regions["answer-boundary"]),
                "all-aligned": len(regions["all-aligned"]),
                "no_prompt_tokens": int(no_encoded.input_ids.numel()),
                "start_prompt_tokens": int(start_encoded.input_ids.numel()),
            },
            "baseline_no_start": compact_surface(baseline),
            "actual_start_target": compact_surface(target),
            "candidate_surface_distance": base_surface_distance,
            "layers": layer_rows,
        })

    timings["experiment_seconds"] = now() - t

    head_summary = []
    for (layer, head), values in sorted(aggregate.items()):
        n = len(values)
        head_summary.append({
            "layer": layer,
            "head": head,
            "n": n,
            "mean_user_mass_delta": sum(x["user_mass_delta"] for x in values) / n,
            "mean_abs_user_mass_delta": sum(abs(x["user_mass_delta"]) for x in values) / n,
            "mean_boundary_mass_delta": sum(x["boundary_mass_delta"] for x in values) / n,
            "mean_abs_boundary_mass_delta": sum(abs(x["boundary_mass_delta"]) for x in values) / n,
            "mean_aligned_raw_l1": sum(x["aligned_raw_l1"] for x in values) / n,
            "mean_aligned_normalized_tv": sum(x["aligned_normalized_tv"] for x in values) / n,
        })

    hidden_summary = []
    for layer, values in sorted(layer_region_hidden.items()):
        n = len(values)
        hidden_summary.append({
            "layer": layer,
            "n": n,
            "mean_user_hidden_cosine_distance": sum(x["user_hidden_cosine_distance"] for x in values) / n,
            "mean_boundary_hidden_cosine_distance": sum(x["boundary_hidden_cosine_distance"] for x in values) / n,
        })

    top_user_heads = sorted(head_summary, key=lambda x: x["mean_abs_user_mass_delta"], reverse=True)[:12]
    top_tv_heads = sorted(head_summary, key=lambda x: x["mean_aligned_normalized_tv"], reverse=True)[:12]
    top_user_hidden_layers = sorted(hidden_summary, key=lambda x: x["mean_user_hidden_cosine_distance"], reverse=True)[:8]

    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(started_wall)}")
    git_sha = os.environ.get("GITHUB_SHA")
    artifact_provenance = {
        "tracked": True,
        "foundry_repository": "SemperSupra/model-artifact-foundry",
        "logical_artifact_id": base.LOGICAL_ID,
        "upstream_provider": "huggingface",
        "upstream_repository": base.MODEL_REPO,
        "upstream_revision": base.MODEL_REVISION,
        "identity_kind": "content-manifest",
        "identity_digest": manifest_digest,
        "foundry_record_ref": None,
        "consumer_selection_ref": f"model-spelunker@{git_sha}" if git_sha else None,
        "verified": True,
        "verification_ref": "foundry-compatible-local-content-manifest",
        "tokenizer_artifact": None,
    }
    observation_hash = "sha256:" + hashlib.sha256(
        json.dumps(observations, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    bundle = {
        "probe_id": "attention-flow-localization-v1",
        "instrument": "aligned-attention-and-regional-residual-cartography",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": base.MODEL_REPO, "revision": base.MODEL_REVISION, "logical_id": base.LOGICAL_ID},
        "artifact_provenance": artifact_provenance,
        "access_tier": "A2",
        "evidence_level": "RELATIONAL",
        "claim_tags": ["LOCALIZED"],
        "observations": {"heldout_tasks": observations},
        "derived_metrics": {
            "head_summary": head_summary,
            "regional_hidden_summary": hidden_summary,
            "top_user_attention_change_heads": top_user_heads,
            "top_aligned_attention_tv_heads": top_tv_heads,
            "top_user_hidden_divergence_layers": top_user_hidden_layers,
            "content_manifest_file_count": len(files),
        },
        "artifacts": [],
        "uncertainty": {
            "status": "information-flow-localization",
            "notes": ["Attention weights are descriptive routing signals, not causal explanations; candidate heads/layers require intervention before promotion."]
        },
        "known_assumptions": [
            "Final answer-boundary query attention is relevant to next-token candidate policy.",
            "Token-identity alignment across protocol conditions is a useful basis for comparing routing to shared semantic regions."
        ],
        "known_failure_modes": [
            "Attention weights need not correspond monotonically to causal contribution.",
            "The inserted protocol prefix changes absolute positions, so routing differences can mix protocol and positional effects."
        ],
        "contradictions": [],
        "cost": {
            **timings,
            "total_seconds": now() - started,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "disk_free_mib_after": (os.statvfs('/tmp').f_bavail * os.statvfs('/tmp').f_frsize) / (1024 * 1024),
        },
        "provenance": {
            "run_id": str(run_id),
            "code_revision": git_sha,
            "model_revision": base.MODEL_REVISION,
            "tokenizer_revision": base.MODEL_REVISION,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "torch": torch.__version__,
                "transformers": __import__("transformers").__version__,
                "attention_implementation": "eager",
                "model_source": "upstream-exact-revision",
                "github_runner_image": os.environ.get("ImageOS"),
                "github_runner_arch": os.environ.get("RUNNER_ARCH"),
            },
            "randomness": {"torch_manual_seed": 0, "generation": "none"},
            "raw_input_hash": None,
            "raw_output_hash": observation_hash,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_id": str(run_id),
        "artifact_identity": manifest_digest,
        "tasks": len(observations),
        "layers": len(hidden_summary),
        "heads": len(head_summary),
        "top_user_attention_change_heads": top_user_heads[:5],
        "top_user_hidden_divergence_layers": top_user_hidden_layers[:5],
        "total_seconds": bundle["cost"]["total_seconds"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
