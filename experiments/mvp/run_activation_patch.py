#!/usr/bin/env python3
"""Rep 13: direct activation patching for the user-start protocol effect.

Patch actual token-present residual states into matched token-absent prompts at
selected layers and aligned prompt positions. Compare direct patches with self
(null) patches and matched-norm random controls.
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
from typing import Any, Callable

import torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer

import run_activation_poke as poke
import run_rep as base

LAYERS = [5, 8]
WIDTHS: list[int | str] = [1, 4, "all"]


def now() -> float:
    return time.perf_counter()


def capture_layer(model: Any, input_ids: torch.Tensor, layer: int) -> tuple[torch.Tensor, torch.Tensor]:
    with torch.inference_mode():
        out = model(input_ids, output_hidden_states=True, use_cache=False)
    layer_seq = out.hidden_states[layer + 1][0].detach().float().cpu()
    final_vec = out.hidden_states[-1][0, -1, :].detach().float().cpu()
    return layer_seq, final_vec


def resolved_width(width: int | str, source_len: int, target_prompt_len: int) -> int:
    if width == "all":
        return min(source_len, target_prompt_len)
    return min(int(width), source_len, target_prompt_len)


def make_patch_hook(
    source_slice: torch.Tensor,
    prompt_len: int,
    mode: str,
    seed: int,
) -> Callable[..., Any]:
    width = int(source_slice.shape[0])

    def hook(_module: Any, _inputs: Any, output: Any):
        hidden0 = output[0] if isinstance(output, tuple) else output
        hidden = hidden0.clone()
        start, end = prompt_len - width, prompt_len
        target = hidden[:, start:end, :]
        source = source_slice.to(device=hidden.device, dtype=hidden.dtype).unsqueeze(0)
        if mode == "direct":
            replacement = source
        elif mode == "self":
            replacement = target.clone()
        elif mode == "random":
            delta = source - target
            wanted = torch.linalg.vector_norm(delta)
            generator = torch.Generator(device=hidden.device)
            generator.manual_seed(seed)
            noise = torch.randn(delta.shape, generator=generator, device=hidden.device, dtype=hidden.dtype)
            noise = noise / torch.clamp(torch.linalg.vector_norm(noise), min=1e-12) * wanted
            replacement = target + noise
        else:
            raise ValueError(mode)
        hidden[:, start:end, :] = replacement
        if isinstance(output, tuple):
            return (hidden,) + output[1:]
        return hidden

    return hook


def run_with_patch(layer_module: Any, source_slice: torch.Tensor, prompt_len: int, mode: str, seed: int, fn: Callable[[], Any]) -> Any:
    handle = layer_module.register_forward_hook(make_patch_hook(source_slice, prompt_len, mode, seed))
    try:
        return fn()
    finally:
        handle.remove()


def patched_candidate_score(
    model: Any,
    tokenizer: Any,
    prompt: str,
    candidate: str,
    layer_module: Any,
    source_slice: torch.Tensor,
    mode: str,
    seed: int,
) -> dict[str, Any]:
    prompt_ids = tokenizer(prompt, return_tensors="pt").input_ids
    candidate_ids = tokenizer(candidate, add_special_tokens=False, return_tensors="pt").input_ids[0]
    full = torch.cat([prompt_ids[0], candidate_ids], dim=0).unsqueeze(0)
    prompt_len = int(prompt_ids.shape[1])

    def forward():
        with torch.inference_mode():
            return model(full, use_cache=False).logits[0]

    logits = run_with_patch(layer_module, source_slice, prompt_len, mode, seed, forward)
    start = prompt_len - 1
    total = 0.0
    tokens = []
    for offset, tok in enumerate(candidate_ids.tolist()):
        lp = torch.log_softmax(logits[start + offset], dim=-1)[tok].item()
        total += lp
        tokens.append({"token_id": int(tok), "logprob": float(lp)})
    n = len(tokens)
    return {
        "candidate": candidate,
        "logprob": float(total),
        "mean_logprob": float(total / n),
        "token_count": n,
        "tokens": tokens,
    }


def patched_surface(
    model: Any,
    tokenizer: Any,
    prompt: str,
    candidates: list[str],
    correct: str,
    layer_module: Any,
    source_slice: torch.Tensor,
    mode: str,
    seed: int,
) -> dict[str, Any]:
    encoded = tokenizer(prompt, return_tensors="pt")
    prompt_len = int(encoded.input_ids.shape[1])

    def hidden_forward():
        with torch.inference_mode():
            return model(**encoded, output_hidden_states=True, use_cache=False)

    out = run_with_patch(layer_module, source_slice, prompt_len, mode, seed, hidden_forward)
    final_vec = out.hidden_states[-1][0, -1, :].detach().float().cpu()
    scores = [
        patched_candidate_score(model, tokenizer, prompt, c, layer_module, source_slice, mode, seed)
        for c in candidates
    ]
    mean_map = {x["candidate"]: float(x["mean_logprob"]) for x in scores}
    order = [k for k, _ in sorted(mean_map.items(), key=lambda item: (-item[1], item[0]))]
    return {
        "prompt_sha256": "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "input_token_ids_sha256": base.token_hash(encoded.input_ids),
        "input_tokens": prompt_len,
        "candidate_scores": scores,
        "candidate_winner": order[0],
        "correct_candidate": correct,
        "correct_rank": order.index(correct) + 1,
        "correct_top1": order[0] == correct,
        "score_vector": [mean_map[c] for c in candidates],
        "final_hidden": final_vec,
    }


def compact(surface: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in surface.items() if k != "final_hidden"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/activation-patch.json"))
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
    model = AutoModelForCausalLM.from_pretrained(model_dir, local_files_only=True, torch_dtype=torch.float32)
    model.eval()
    layers = poke.get_layers(model)
    timings["model_load_seconds"] = now() - t

    observations: list[dict[str, Any]] = []
    aggregate: dict[str, list[dict[str, float]]] = {}
    self_max_surface_delta = 0.0
    self_max_hidden_delta = 0.0
    t = now()

    for task_index, task in enumerate(poke.HELDOUT):
        no_prompt = poke.render(task["user"], False)
        start_prompt = poke.render(task["user"], True)
        baseline = poke.condition_surface(model, tokenizer, no_prompt, task["candidates"], task["correct"])
        target = poke.condition_surface(model, tokenizer, start_prompt, task["candidates"], task["correct"])
        base_surface_distance = poke.centered_distance(baseline["score_vector"], target["score_vector"])
        base_hidden_distance = poke.cosine_distance(baseline["final_hidden"], target["final_hidden"])

        no_ids = tokenizer(no_prompt, return_tensors="pt").input_ids
        start_ids = tokenizer(start_prompt, return_tensors="pt").input_ids
        interventions = []

        for layer in LAYERS:
            start_seq, _ = capture_layer(model, start_ids, layer)
            no_seq, _ = capture_layer(model, no_ids, layer)
            for width_spec in WIDTHS:
                width = resolved_width(width_spec, len(start_seq), int(no_ids.shape[1]))
                source_slice = start_seq[-width:, :]
                self_slice = no_seq[-width:, :]
                variants = [
                    ("direct", source_slice),
                    ("self", self_slice),
                    ("random", source_slice),
                ]
                for mode, patch_slice in variants:
                    seed = 13000 + task_index * 100 + layer * 10 + width
                    surface = patched_surface(
                        model, tokenizer, no_prompt, task["candidates"], task["correct"],
                        layers[layer], patch_slice, mode, seed,
                    )
                    surface_distance = poke.centered_distance(surface["score_vector"], target["score_vector"])
                    hidden_distance = poke.cosine_distance(surface["final_hidden"], target["final_hidden"])
                    surface_progress = 1.0 - surface_distance / base_surface_distance if base_surface_distance > 1e-12 else 0.0
                    hidden_progress = 1.0 - hidden_distance / base_hidden_distance if base_hidden_distance > 1e-12 else 0.0
                    record = {
                        "layer": layer,
                        "width_spec": str(width_spec),
                        "width_tokens": width,
                        "control_type": mode,
                        "surface_distance_to_start": surface_distance,
                        "surface_progress_to_start": surface_progress,
                        "final_hidden_cosine_distance_to_start": hidden_distance,
                        "hidden_progress_to_start": hidden_progress,
                        "surface": compact(surface),
                    }
                    interventions.append(record)
                    key = f"L{layer}:W{width_spec}:{mode}"
                    aggregate.setdefault(key, []).append({
                        "surface_progress": surface_progress,
                        "hidden_progress": hidden_progress,
                        "correct_top1": float(surface["correct_top1"]),
                    })
                    if mode == "self":
                        self_max_surface_delta = max(
                            self_max_surface_delta,
                            max(abs(a - b) for a, b in zip(surface["score_vector"], baseline["score_vector"])),
                        )
                        self_max_hidden_delta = max(
                            self_max_hidden_delta,
                            poke.cosine_distance(surface["final_hidden"], baseline["final_hidden"]),
                        )

        observations.append({
            "task_id": task["task_id"],
            "user_sha256": "sha256:" + hashlib.sha256(task["user"].encode("utf-8")).hexdigest(),
            "candidates": task["candidates"],
            "correct": task["correct"],
            "baseline_no_start": compact(baseline),
            "actual_start_target": compact(target),
            "baseline_surface_distance_to_start": base_surface_distance,
            "baseline_final_hidden_cosine_distance_to_start": base_hidden_distance,
            "interventions": interventions,
        })

    timings["heldout_experiment_seconds"] = now() - t

    derived = {}
    for key, values in sorted(aggregate.items()):
        derived[key] = {
            "n": len(values),
            "mean_surface_progress_to_start": sum(x["surface_progress"] for x in values) / len(values),
            "mean_hidden_progress_to_start": sum(x["hidden_progress"] for x in values) / len(values),
            "top1_correct_rate": sum(x["correct_top1"] for x in values) / len(values),
        }

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
        "probe_id": "activation-patch-v1",
        "instrument": "direct-residual-stream-token-state-patching",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": base.MODEL_REPO, "revision": base.MODEL_REVISION, "logical_id": base.LOGICAL_ID},
        "artifact_provenance": artifact_provenance,
        "access_tier": "A4",
        "evidence_level": "CAUSAL",
        "claim_tags": ["LOCALIZED"],
        "observations": {"heldout_tasks": observations},
        "derived_metrics": {
            "aggregate_variants": derived,
            "self_patch_max_surface_logprob_delta": self_max_surface_delta,
            "self_patch_max_final_hidden_cosine_distance": self_max_hidden_delta,
            "content_manifest_file_count": len(files),
        },
        "artifacts": [],
        "uncertainty": {"status": "causal-mechanism-localization", "notes": ["Direct patching tests state sufficiency at selected layers/positions; it does not establish uniqueness of mechanism."]},
        "known_assumptions": ["Prompt positions are causally independent of appended candidate tokens.", "Tail alignment from the answer boundary is the intended cross-protocol position mapping."],
        "known_failure_modes": ["Whole-suffix patching may copy task-specific content state as well as protocol state.", "A successful patch does not imply a portable additive steering direction."],
        "contradictions": [],
        "cost": {
            **timings,
            "total_seconds": now() - started,
            "peak_rss_mib": poke.peak_rss_mib(),
            "disk_free_mib_after": poke.disk_free_mib(Path("/tmp")),
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
                "model_source": "upstream-exact-revision",
                "github_runner_image": os.environ.get("ImageOS"),
                "github_runner_arch": os.environ.get("RUNNER_ARCH"),
            },
            "randomness": {"torch_manual_seed": 0, "random_patch_seeds": "deterministic-per-task-layer-width"},
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
        "variants": len(derived),
        "self_patch_max_surface_delta": self_max_surface_delta,
        "self_patch_max_hidden_distance": self_max_hidden_delta,
        "total_seconds": bundle["cost"]["total_seconds"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
