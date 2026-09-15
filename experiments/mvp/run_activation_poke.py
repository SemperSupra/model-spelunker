#!/usr/bin/env python3
"""Rep 12: causal residual-stream POKE test for the user-start protocol direction.

Derive the mean activation difference induced by `<|im_start|>user` on calibration
prompts, then inject that direction into held-out no-start prompts. Compare the
intervened candidate surface and final representation with the actual start-token
condition. Includes negative-direction and matched-norm random controls.
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

import run_rep as base

LAYERS = [5, 8]
ALPHAS = [-1.0, 0.5, 1.0, 2.0]
ANSWER_TAIL = "<|im_start|>assistant\nAnswer: "

CALIBRATION = [
    "Compute 9 x 6.",
    "Compute 17 + 8.",
    "What is the capital of France?",
    "Which number is larger, 0.65 or 0.70?",
]

HELDOUT = [
    {
        "task_id": "mul-6x7",
        "user": "Compute 6 x 7.",
        "correct": "42",
        "candidates": ["35", "40", "42", "48", "49"],
    },
    {
        "task_id": "add-14-9",
        "user": "Compute 14 + 9.",
        "correct": "23",
        "candidates": ["21", "22", "23", "24", "25"],
    },
    {
        "task_id": "capital-italy",
        "user": "What is the capital of Italy?",
        "correct": "Rome",
        "candidates": ["Rome", "Paris", "Milan", "Berlin", "Madrid"],
    },
    {
        "task_id": "month-after-january",
        "user": "Which month comes immediately after January?",
        "correct": "February",
        "candidates": ["February", "March", "April", "June", "December"],
    },
]


def now() -> float:
    return time.perf_counter()


def render(user: str, start_present: bool) -> str:
    prefix = "<|im_start|>user\n" if start_present else ""
    return f"{prefix}{user}\n{ANSWER_TAIL}"


def get_layers(model: Any):
    core = getattr(model, "model", None)
    layers = getattr(core, "layers", None)
    if layers is None:
        raise RuntimeError("expected decoder layers at model.model.layers")
    if max(LAYERS) >= len(layers):
        raise RuntimeError(f"requested layer {max(LAYERS)} but model has {len(layers)} layers")
    return layers


def hidden_at(model: Any, tokenizer: Any, prompt: str, layer: int) -> tuple[torch.Tensor, torch.Tensor]:
    encoded = tokenizer(prompt, return_tensors="pt")
    with torch.inference_mode():
        out = model(**encoded, output_hidden_states=True, use_cache=False)
    # hidden_states[0] is embedding output; layer N output is N+1.
    layer_vec = out.hidden_states[layer + 1][0, -1, :].detach().float().cpu()
    final_vec = out.hidden_states[-1][0, -1, :].detach().float().cpu()
    return layer_vec, final_vec


def make_hook(delta: torch.Tensor, position: int) -> Callable[..., Any]:
    def hook(_module: Any, _inputs: Any, output: Any):
        if isinstance(output, tuple):
            hidden = output[0].clone()
            pos = position if position >= 0 else hidden.shape[1] + position
            hidden[:, pos, :] = hidden[:, pos, :] + delta.to(device=hidden.device, dtype=hidden.dtype)
            return (hidden,) + output[1:]
        hidden = output.clone()
        pos = position if position >= 0 else hidden.shape[1] + position
        hidden[:, pos, :] = hidden[:, pos, :] + delta.to(device=hidden.device, dtype=hidden.dtype)
        return hidden
    return hook


def run_with_hook(layer_module: Any, delta: torch.Tensor, position: int, fn: Callable[[], Any]) -> Any:
    handle = layer_module.register_forward_hook(make_hook(delta, position))
    try:
        return fn()
    finally:
        handle.remove()


def candidate_score(
    model: Any,
    tokenizer: Any,
    prompt: str,
    candidate: str,
    layer_module: Any | None = None,
    delta: torch.Tensor | None = None,
) -> dict[str, Any]:
    prompt_ids = tokenizer(prompt, return_tensors="pt").input_ids
    candidate_ids = tokenizer(candidate, add_special_tokens=False, return_tensors="pt").input_ids[0]
    if candidate_ids.numel() == 0:
        raise RuntimeError(f"candidate tokenized empty: {candidate!r}")
    full = torch.cat([prompt_ids[0], candidate_ids], dim=0).unsqueeze(0)
    prompt_last = prompt_ids.shape[1] - 1

    def forward():
        with torch.inference_mode():
            return model(full, use_cache=False).logits[0]

    logits = (
        run_with_hook(layer_module, delta, prompt_last, forward)
        if layer_module is not None and delta is not None
        else forward()
    )
    total = 0.0
    per_token = []
    for offset, tok in enumerate(candidate_ids.tolist()):
        lp = torch.log_softmax(logits[prompt_last + offset], dim=-1)[tok].item()
        total += lp
        per_token.append({"token_id": int(tok), "logprob": float(lp)})
    n = len(per_token)
    return {
        "candidate": candidate,
        "logprob": float(total),
        "mean_logprob": float(total / n),
        "token_count": n,
        "tokens": per_token,
    }


def condition_surface(
    model: Any,
    tokenizer: Any,
    prompt: str,
    candidates: list[str],
    correct: str,
    layer_module: Any | None = None,
    delta: torch.Tensor | None = None,
) -> dict[str, Any]:
    encoded = tokenizer(prompt, return_tensors="pt")
    prompt_last = encoded.input_ids.shape[1] - 1

    def hidden_forward():
        with torch.inference_mode():
            return model(**encoded, output_hidden_states=True, use_cache=False)

    out = (
        run_with_hook(layer_module, delta, prompt_last, hidden_forward)
        if layer_module is not None and delta is not None
        else hidden_forward()
    )
    final_vec = out.hidden_states[-1][0, -1, :].detach().float().cpu()
    scores = [candidate_score(model, tokenizer, prompt, c, layer_module, delta) for c in candidates]
    mean_map = {x["candidate"]: float(x["mean_logprob"]) for x in scores}
    order = [k for k, _ in sorted(mean_map.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {
        "prompt_sha256": "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "input_token_ids_sha256": base.token_hash(encoded.input_ids),
        "input_tokens": int(encoded.input_ids.numel()),
        "candidate_scores": scores,
        "candidate_winner": order[0],
        "correct_candidate": correct,
        "correct_rank": order.index(correct) + 1,
        "correct_top1": order[0] == correct,
        "score_vector": [mean_map[c] for c in candidates],
        "final_hidden": final_vec,
    }


def centered_distance(a: list[float], b: list[float]) -> float:
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    return math.sqrt(sum(((x - ma) - (y - mb)) ** 2 for x, y in zip(a, b)) / len(a))


def cosine_distance(a: torch.Tensor, b: torch.Tensor) -> float:
    denom = max(float(torch.linalg.vector_norm(a).item() * torch.linalg.vector_norm(b).item()), 1e-12)
    return 1.0 - float(torch.dot(a, b).item() / denom)


def compact_surface(surface: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in surface.items() if k != "final_hidden"}


def peak_rss_mib() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def disk_free_mib(path: Path) -> float:
    stat = os.statvfs(path)
    return (stat.f_bavail * stat.f_frsize) / (1024 * 1024)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/activation-poke.json"))
    args = parser.parse_args()

    started_wall = time.time()
    started = now()
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
    layers = get_layers(model)
    timings["model_load_seconds"] = now() - t

    # Derive a task-averaged user-start direction at each selected residual layer.
    calibration: dict[int, dict[str, Any]] = {}
    directions: dict[int, torch.Tensor] = {}
    random_controls: dict[int, torch.Tensor] = {}
    t = now()
    for layer in LAYERS:
        deltas = []
        per_prompt = []
        for user in CALIBRATION:
            start_vec, _ = hidden_at(model, tokenizer, render(user, True), layer)
            no_vec, _ = hidden_at(model, tokenizer, render(user, False), layer)
            delta = start_vec - no_vec
            deltas.append(delta)
            per_prompt.append({
                "user_sha256": "sha256:" + hashlib.sha256(user.encode("utf-8")).hexdigest(),
                "delta_l2": float(torch.linalg.vector_norm(delta).item()),
                "cosine_distance": cosine_distance(start_vec, no_vec),
            })
        direction = torch.stack(deltas).mean(dim=0)
        directions[layer] = direction
        norm = float(torch.linalg.vector_norm(direction).item())
        generator = torch.Generator(device="cpu")
        generator.manual_seed(12000 + layer)
        random_vec = torch.randn(direction.shape, generator=generator, dtype=direction.dtype)
        random_vec = random_vec / max(float(torch.linalg.vector_norm(random_vec).item()), 1e-12) * norm
        random_controls[layer] = random_vec
        calibration[layer] = {
            "layer": layer,
            "calibration_prompt_count": len(CALIBRATION),
            "direction_l2": norm,
            "random_control_l2": float(torch.linalg.vector_norm(random_vec).item()),
            "per_prompt": per_prompt,
        }
    timings["direction_derivation_seconds"] = now() - t

    observations = []
    aggregate: dict[str, list[dict[str, float]]] = {}
    t = now()
    for task in HELDOUT:
        no_prompt = render(task["user"], False)
        start_prompt = render(task["user"], True)
        baseline = condition_surface(model, tokenizer, no_prompt, task["candidates"], task["correct"])
        target = condition_surface(model, tokenizer, start_prompt, task["candidates"], task["correct"])
        base_surface_distance = centered_distance(baseline["score_vector"], target["score_vector"])
        base_hidden_distance = cosine_distance(baseline["final_hidden"], target["final_hidden"])

        interventions = []
        for layer in LAYERS:
            variants: list[tuple[str, torch.Tensor, str, float]] = []
            for alpha in ALPHAS:
                variants.append((f"direction-alpha-{alpha:g}", directions[layer] * alpha, "direction", alpha))
            variants.append(("random-matched-alpha-1", random_controls[layer], "random", 1.0))

            for variant_id, delta, control_type, alpha in variants:
                surface = condition_surface(
                    model,
                    tokenizer,
                    no_prompt,
                    task["candidates"],
                    task["correct"],
                    layers[layer],
                    delta,
                )
                surface_distance = centered_distance(surface["score_vector"], target["score_vector"])
                hidden_distance = cosine_distance(surface["final_hidden"], target["final_hidden"])
                surface_progress = (
                    1.0 - surface_distance / base_surface_distance
                    if base_surface_distance > 1e-12 else 0.0
                )
                hidden_progress = (
                    1.0 - hidden_distance / base_hidden_distance
                    if base_hidden_distance > 1e-12 else 0.0
                )
                record = {
                    "layer": layer,
                    "variant_id": variant_id,
                    "control_type": control_type,
                    "alpha": alpha,
                    "delta_l2": float(torch.linalg.vector_norm(delta).item()),
                    "surface_distance_to_start": surface_distance,
                    "surface_progress_to_start": surface_progress,
                    "final_hidden_cosine_distance_to_start": hidden_distance,
                    "hidden_progress_to_start": hidden_progress,
                    "surface": compact_surface(surface),
                }
                interventions.append(record)
                key = f"L{layer}:{variant_id}"
                aggregate.setdefault(key, []).append({
                    "surface_progress": surface_progress,
                    "hidden_progress": hidden_progress,
                    "correct_top1": float(surface["correct_top1"]),
                })

        observations.append({
            "task_id": task["task_id"],
            "user_sha256": "sha256:" + hashlib.sha256(task["user"].encode("utf-8")).hexdigest(),
            "candidates": task["candidates"],
            "correct": task["correct"],
            "baseline_no_start": compact_surface(baseline),
            "actual_start_target": compact_surface(target),
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
    bundle = {
        "probe_id": "activation-poke-v1",
        "instrument": "residual-stream-user-start-direction-poke",
        "instrument_version": "mvp-1",
        "model_identity": {
            "repository": base.MODEL_REPO,
            "revision": base.MODEL_REVISION,
            "logical_id": base.LOGICAL_ID,
        },
        "artifact_provenance": {
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
        },
        "access_tier": "A4",
        "evidence_level": "CAUSAL",
        "claim_tags": ["LOCALIZED"],
        "observations": {
            "calibration": [calibration[layer] for layer in LAYERS],
            "heldout_tasks": observations,
        },
        "derived_metrics": {
            "layers": LAYERS,
            "alphas": ALPHAS,
            "calibration_prompt_count": len(CALIBRATION),
            "heldout_task_count": len(HELDOUT),
            "aggregate_variants": derived,
            "content_manifest_file_count": len(files),
        },
        "artifacts": [],
        "uncertainty": {
            "status": "first-causal-rep",
            "notes": [
                "A single successful intervention rep does not establish a stable model control register.",
                "The derived direction includes both protocol semantics and positional consequences of adding the start token.",
            ],
        },
        "known_assumptions": [
            "hidden_states[N+1] corresponds to decoder layer N output for this architecture.",
            "Mean candidate token log-probability is used for neighborhoods with unequal token lengths.",
            "The intervention is applied only at the prompt-boundary token after the selected decoder layer.",
        ],
        "known_failure_modes": [
            "A direction may overfit calibration prompts and fail held-out prompts.",
            "Matched-norm random controls do not exhaust all possible non-specific intervention controls.",
            "Moving a candidate surface toward the token-present state is not equivalent to improving task capability.",
        ],
        "contradictions": [],
        "cost": {
            **timings,
            "total_seconds": now() - started,
            "peak_rss_mib": peak_rss_mib(),
            "disk_free_mib_after": disk_free_mib(Path("/tmp")),
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
                "github_runner_image": os.environ.get("ImageOS"),
                "github_runner_arch": os.environ.get("RUNNER_ARCH"),
            },
            "randomness": {
                "torch_manual_seed": 0,
                "random_control_seed_rule": "12000 + layer",
            },
            "raw_input_hash": "sha256:" + hashlib.sha256(
                json.dumps({"calibration": CALIBRATION, "heldout": HELDOUT, "layers": LAYERS, "alphas": ALPHAS}, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "raw_output_hash": None,
        },
    }

    raw_for_hash = json.dumps(bundle["observations"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    bundle["provenance"]["raw_output_hash"] = "sha256:" + hashlib.sha256(raw_for_hash).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_id": str(run_id),
        "artifact_identity": manifest_digest,
        "layers": LAYERS,
        "heldout_tasks": len(HELDOUT),
        "total_seconds": bundle["cost"]["total_seconds"],
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
