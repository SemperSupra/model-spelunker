#!/usr/bin/env python3
"""Rep 20: cross-model portability of the core Model Spelunker instruments.

Run a small fixed probe set against Qwen2.5-0.5B-Instruct using the same generic
instrument classes already exercised on SmolLM2: behavioral/candidate surfaces,
layerwise residual summaries, protocol contrasts, and attention-head discovery.
The goal is instrument/method portability, not a claim that the same SmolLM
mechanisms or control recipes should transfer.
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

import torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer

import run_rep as base

MODEL_REPO = "Qwen/Qwen2.5-0.5B-Instruct"
MODEL_REVISION = "ec7ddfa904d4d447eedd0b7f126df16957734abb"
LOGICAL_ID = "llm/qwen2.5/0.5b-instruct"
ALLOW_PATTERNS = ["*.json", "*.safetensors", "*.txt", "*.jinja", "*.model"]

TASKS = [
    {"task_id": "portable-mul", "user": "Compute 8 x 9.", "correct": "72", "candidates": ["64", "70", "72", "81", "88"]},
    {"task_id": "portable-sub", "user": "Compute 31 - 14.", "correct": "17", "candidates": ["15", "16", "17", "18", "19"]},
    {"task_id": "portable-capital", "user": "What is the capital of Japan?", "correct": "Tokyo", "candidates": ["Tokyo", "Kyoto", "Osaka", "Seoul", "Beijing"]},
    {"task_id": "portable-planet", "user": "Which planet is known as the Red Planet?", "correct": "Mars", "candidates": ["Mars", "Venus", "Jupiter", "Mercury", "Saturn"]},
    {"task_id": "portable-month", "user": "Which month comes immediately before April?", "correct": "March", "candidates": ["January", "February", "March", "May", "June"]},
    {"task_id": "portable-decimal", "user": "Which number is larger, 0.42 or 0.37?", "correct": "0.42", "candidates": ["0.32", "0.37", "0.40", "0.42", "0.47"]},
]

CONDITIONS = ["native", "raw", "newline_raw"]


def now() -> float:
    return time.perf_counter()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def content_manifest(root: Path) -> tuple[str, list[dict[str, Any]]]:
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".cache" not in p.parts):
        rel = path.relative_to(root).as_posix()
        files.append({"path": rel, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if not files:
        raise RuntimeError("no model artifact files found")
    material = {
        "schema_version": 1,
        "logical_id": LOGICAL_ID,
        "upstream": {"provider": "huggingface", "repository": MODEL_REPO, "exact_revision": MODEL_REVISION},
        "files": files,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest(), files


def render(tokenizer: Any, user: str, condition: str) -> str:
    if condition == "native":
        return tokenizer.apply_chat_template(
            [{"role": "user", "content": user}], tokenize=False, add_generation_prompt=True
        )
    if condition == "raw":
        return f"{user}\nAnswer: "
    if condition == "newline_raw":
        return f"\n{user}\nAnswer: "
    raise ValueError(condition)


def candidate_score(model: Any, tokenizer: Any, prompt: str, candidate: str) -> dict[str, Any]:
    prompt_ids = tokenizer(prompt, return_tensors="pt").input_ids
    cand_ids = tokenizer(candidate, add_special_tokens=False, return_tensors="pt").input_ids[0]
    if cand_ids.numel() == 0:
        raise RuntimeError(f"empty candidate tokens: {candidate!r}")
    full = torch.cat([prompt_ids[0], cand_ids], dim=0).unsqueeze(0)
    with torch.inference_mode():
        logits = model(full, use_cache=False).logits[0]
    start = int(prompt_ids.shape[1]) - 1
    total = 0.0
    token_rows = []
    for offset, tok in enumerate(cand_ids.tolist()):
        lp = float(torch.log_softmax(logits[start + offset], dim=-1)[tok].item())
        total += lp
        token_rows.append({"token_id": int(tok), "logprob": lp})
    return {
        "candidate": candidate,
        "logprob": total,
        "mean_logprob": total / len(token_rows),
        "token_count": len(token_rows),
        "tokens": token_rows,
    }


def cosine_distance(a: torch.Tensor, b: torch.Tensor) -> float:
    denom = max(float(torch.linalg.vector_norm(a).item() * torch.linalg.vector_norm(b).item()), 1e-12)
    return 1.0 - float(torch.dot(a, b).item() / denom)


def condition_surface(model: Any, tokenizer: Any, prompt: str, task: dict[str, Any]) -> tuple[dict[str, Any], list[torch.Tensor], tuple[torch.Tensor, ...]]:
    encoded = tokenizer(prompt, return_tensors="pt")
    with torch.inference_mode():
        out = model(**encoded, output_hidden_states=True, output_attentions=True, use_cache=False)
    if out.attentions is None:
        raise RuntimeError("model did not return attention tensors under eager instrumentation")

    vectors = [x[0, -1, :].detach().float().cpu() for x in out.hidden_states]
    hidden_summary = [
        {
            "layer": i,
            "l2": float(torch.linalg.vector_norm(v).item()),
            "mean": float(v.mean().item()),
            "std": float(v.std(unbiased=False).item()),
        }
        for i, v in enumerate(vectors)
    ]

    scores = [candidate_score(model, tokenizer, prompt, c) for c in task["candidates"]]
    mean_map = {x["candidate"]: float(x["mean_logprob"]) for x in scores}
    order = [k for k, _ in sorted(mean_map.items(), key=lambda kv: (-kv[1], kv[0]))]
    correct = task["correct"]
    margin = mean_map[correct] - max(v for k, v in mean_map.items() if k != correct)

    with torch.inference_mode():
        generated = model.generate(
            **encoded,
            max_new_tokens=12,
            do_sample=False,
            use_cache=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    new_ids = generated[0, encoded.input_ids.shape[1]:]
    generation = tokenizer.decode(new_ids, skip_special_tokens=False).strip()

    # Model-agnostic attention-sink discovery: final query attention to the first
    # one and first two key positions, aggregated later across tasks.
    head_rows = []
    for layer, attn_t in enumerate(out.attentions):
        attn = attn_t[0].detach().float().cpu()  # [heads, q, k]
        q = attn.shape[1] - 1
        for head in range(attn.shape[0]):
            first1 = float(attn[head, q, 0].item())
            first2 = float(attn[head, q, : min(2, attn.shape[-1])].sum().item())
            entropy_vec = attn[head, q]
            entropy = float((-(entropy_vec * torch.log(torch.clamp(entropy_vec, min=1e-12))).sum()).item())
            head_rows.append({"layer": layer, "head": head, "first1_mass": first1, "first2_mass": first2, "entropy": entropy})

    surface = {
        "prompt_sha256": "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "input_token_ids_sha256": base.token_hash(encoded.input_ids),
        "input_tokens": int(encoded.input_ids.numel()),
        "candidate_scores": scores,
        "candidate_winner": order[0],
        "correct_rank": order.index(correct) + 1,
        "correct_top1": order[0] == correct,
        "correct_margin": margin,
        "generation": generation,
        "hidden_summary": hidden_summary,
        "attention_heads": head_rows,
    }
    return surface, vectors, out.attentions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/cross-model-portability.json"))
    args = parser.parse_args()

    started_wall, started = time.time(), now()
    timings: dict[str, float] = {}
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    torch.manual_seed(0)

    t = now()
    model_dir = Path(snapshot_download(
        repo_id=MODEL_REPO,
        revision=MODEL_REVISION,
        allow_patterns=ALLOW_PATTERNS,
        local_dir="/tmp/model-spelunker-qwen2.5-0.5b",
    )).resolve()
    timings["hydrate_seconds"] = now() - t

    t = now()
    manifest_digest, manifest_files = content_manifest(model_dir)
    timings["artifact_verify_seconds"] = now() - t

    t = now()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    if not tokenizer.chat_template:
        raise RuntimeError("second model has no chat template; portability rep requires native serialization")
    model = AutoModelForCausalLM.from_pretrained(
        model_dir,
        local_files_only=True,
        torch_dtype=torch.float32,
        attn_implementation="eager",
    )
    model.eval()
    timings["model_load_seconds"] = now() - t

    observations = []
    attention_aggregate: dict[tuple[str, int, int], list[dict[str, float]]] = {}
    protocol_contrasts = []
    t = now()

    for task in TASKS:
        task_conditions: dict[str, Any] = {}
        condition_vectors: dict[str, list[torch.Tensor]] = {}
        for condition in CONDITIONS:
            prompt = render(tokenizer, task["user"], condition)
            surface, vectors, _ = condition_surface(model, tokenizer, prompt, task)
            task_conditions[condition] = surface
            condition_vectors[condition] = vectors
            for row in surface["attention_heads"]:
                attention_aggregate.setdefault((condition, row["layer"], row["head"]), []).append({
                    "first1_mass": row["first1_mass"],
                    "first2_mass": row["first2_mass"],
                    "entropy": row["entropy"],
                })

        if len(condition_vectors["native"]) != len(condition_vectors["raw"]):
            raise RuntimeError("hidden-state layer count mismatch across protocol conditions")
        layer_contrast = []
        for layer, (a, b) in enumerate(zip(condition_vectors["raw"], condition_vectors["native"])):
            layer_contrast.append({
                "layer": layer,
                "raw_native_cosine_distance": cosine_distance(a, b),
                "delta_l2": float(torch.linalg.vector_norm(b - a).item()),
            })
        protocol_contrasts.append({"task_id": task["task_id"], "layers": layer_contrast})
        observations.append({
            "task_id": task["task_id"],
            "user_sha256": "sha256:" + hashlib.sha256(task["user"].encode("utf-8")).hexdigest(),
            "correct": task["correct"],
            "conditions": task_conditions,
        })

    timings["experiment_seconds"] = now() - t

    top_heads_by_condition = {}
    for condition in CONDITIONS:
        rows = []
        for (cond, layer, head), values in attention_aggregate.items():
            if cond != condition:
                continue
            n = len(values)
            rows.append({
                "layer": layer,
                "head": head,
                "n": n,
                "mean_first1_mass": sum(x["first1_mass"] for x in values) / n,
                "mean_first2_mass": sum(x["first2_mass"] for x in values) / n,
                "mean_entropy": sum(x["entropy"] for x in values) / n,
            })
        top_heads_by_condition[condition] = sorted(rows, key=lambda x: x["mean_first1_mass"], reverse=True)[:12]

    layer_count = len(protocol_contrasts[0]["layers"])
    mean_protocol_contrast = []
    for layer in range(layer_count):
        vals = [x["layers"][layer] for x in protocol_contrasts]
        mean_protocol_contrast.append({
            "layer": layer,
            "mean_raw_native_cosine_distance": sum(x["raw_native_cosine_distance"] for x in vals) / len(vals),
            "mean_delta_l2": sum(x["delta_l2"] for x in vals) / len(vals),
        })

    condition_summary = {}
    for condition in CONDITIONS:
        rows = [x["conditions"][condition] for x in observations]
        condition_summary[condition] = {
            "top1_rate": sum(float(x["correct_top1"]) for x in rows) / len(rows),
            "mean_correct_rank": sum(float(x["correct_rank"]) for x in rows) / len(rows),
            "mean_correct_margin": sum(float(x["correct_margin"]) for x in rows) / len(rows),
            "mean_input_tokens": sum(float(x["input_tokens"]) for x in rows) / len(rows),
        }

    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(started_wall)}")
    git_sha = os.environ.get("GITHUB_SHA")
    observation_hash = "sha256:" + hashlib.sha256(
        json.dumps(observations, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    bundle = {
        "probe_id": "cross-model-portability-qwen25-v1",
        "instrument": "portable-behavior-logprob-residual-attention-suite",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": MODEL_REPO, "revision": MODEL_REVISION, "logical_id": LOGICAL_ID},
        "artifact_provenance": {
            "tracked": True,
            "foundry_repository": "SemperSupra/model-artifact-foundry",
            "logical_artifact_id": LOGICAL_ID,
            "upstream_provider": "huggingface",
            "upstream_repository": MODEL_REPO,
            "upstream_revision": MODEL_REVISION,
            "identity_kind": "content-manifest",
            "identity_digest": manifest_digest,
            "foundry_record_ref": None,
            "consumer_selection_ref": f"model-spelunker@{git_sha}" if git_sha else None,
            "verified": True,
            "verification_ref": "foundry-compatible-local-content-manifest",
            "tokenizer_artifact": None,
        },
        "access_tier": "A2",
        "evidence_level": "REPRODUCED",
        "claim_tags": [],
        "observations": {"tasks": observations, "protocol_contrasts": protocol_contrasts},
        "derived_metrics": {
            "condition_summary": condition_summary,
            "mean_raw_native_layer_contrast": mean_protocol_contrast,
            "top_first_token_attention_heads": top_heads_by_condition,
            "content_manifest_file_count": len(manifest_files),
            "portable_instrument_checks": {
                "native_chat_template": True,
                "candidate_surface": True,
                "hidden_states": True,
                "attention_tensors": True,
                "greedy_generation": True,
            },
        },
        "artifacts": [],
        "uncertainty": {
            "status": "instrument-portability-rep",
            "notes": [
                "This rep tests whether generic Model Spelunker instruments work unchanged on another model family; it does not assert transfer of SmolLM-specific mechanisms.",
                "Protocol conditions intentionally differ in serialization and may differ in endpoint semantics; contrasts are descriptive, not causal attribution.",
            ],
        },
        "known_assumptions": ["Transformers eager attention faithfully exposes Qwen2.5 attention tensors for this runtime."],
        "known_failure_modes": ["A model-specific chat template can change endpoint semantics; do not interpret raw/native differences as one-token causal effects."],
        "contradictions": [],
        "cost": {
            **timings,
            "total_seconds": now() - started,
            "peak_rss_mib": (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
            "disk_free_mib_after": base.disk_free_mib(Path("/tmp")),
        },
        "provenance": {
            "run_id": str(run_id),
            "code_revision": git_sha,
            "model_revision": MODEL_REVISION,
            "tokenizer_revision": MODEL_REVISION,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "torch": torch.__version__,
                "transformers": __import__("transformers").__version__,
                "github_runner_image": os.environ.get("ImageOS"),
                "github_runner_arch": os.environ.get("RUNNER_ARCH"),
            },
            "randomness": {"torch_manual_seed": 0, "generation": "greedy"},
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
        "conditions": condition_summary,
        "top_native_attention_heads": top_heads_by_condition["native"][:5],
        "cost": bundle["cost"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
