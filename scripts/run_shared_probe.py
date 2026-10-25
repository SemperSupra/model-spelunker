#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import resource
import time
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_probe_set(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise RuntimeError("unsupported probe schema")
    cases = data.get("cases") or []
    ids = [c.get("probe_case_id") for c in cases]
    if not cases or any(not x for x in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("probe_case_id values must be non-empty and unique")
    for case in cases:
        render = case.get("render")
        if render == "chat" and not case.get("messages"):
            raise RuntimeError(f"{case['probe_case_id']}: chat case missing messages")
        if render == "raw" and not isinstance(case.get("prompt"), str):
            raise RuntimeError(f"{case['probe_case_id']}: raw case missing prompt")
        if render not in {"chat", "raw"}:
            raise RuntimeError(f"{case['probe_case_id']}: unsupported render mode")
    return data


def validate_foundry_identity(data: dict[str, Any]) -> None:
    required = {
        "logical_id",
        "upstream_repository",
        "upstream_exact_revision",
        "identity_kind",
        "identity_digest",
        "foundry_ref",
        "hydration_verified",
    }
    missing = sorted(required - set(data))
    if missing:
        raise RuntimeError(f"foundry identity missing fields: {missing}")
    if data["identity_kind"] not in {"oci", "content-manifest"}:
        raise RuntimeError("identity_kind must be oci or content-manifest")
    digest = str(data["identity_digest"])
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise RuntimeError("identity_digest must be a sha256 digest")
    if data["hydration_verified"] is not True:
        raise RuntimeError("Foundry hydration must be verified before inference")


def render_case(tokenizer: Any, case: dict[str, Any]) -> str:
    if case["render"] == "raw":
        return case["prompt"]
    return tokenizer.apply_chat_template(
        case["messages"], tokenize=False, add_generation_prompt=True
    )


def vector_summary(tensor: Any) -> dict[str, float]:
    v = tensor.detach().float().cpu()
    return {
        "mean": float(v.mean().item()),
        "std": float(v.std(unbiased=False).item()),
        "l2": float(v.norm().item()),
        "max_abs": float(v.abs().max().item()),
    }


def summarize_batch_timing(timing: dict[str, float], probe_seconds: list[float]) -> dict[str, float | int | None]:
    n = len(probe_seconds)
    p = sum(probe_seconds) / n if n else 0.0
    setup_keys = [
        "dependency_setup_seconds",
        "artifact_hydration_seconds",
        "artifact_verification_seconds",
        "model_load_seconds",
        "instrumentation_init_seconds",
    ]
    s = sum(float(timing.get(k, 0.0)) for k in setup_keys)
    denom = s + n * p
    target_fraction = 0.20
    if p <= 0 or target_fraction <= 0:
        break_even = None
    else:
        break_even = math.ceil((s * (1 - target_fraction)) / (target_fraction * p))
    return {
        "probe_count": n,
        "fixed_setup_seconds": s,
        "mean_marginal_probe_seconds": p,
        "setup_fraction": (s / denom) if denom else 0.0,
        "throughput_probes_per_minute": (60.0 * n / sum(probe_seconds)) if probe_seconds and sum(probe_seconds) else 0.0,
        "break_even_batch_size_at_20pct_setup": break_even,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    probe_set = load_probe_set(args.probes)
    foundry = json.loads(args.foundry_identity.read_text(encoding="utf-8"))
    validate_foundry_identity(foundry)

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    random.seed(args.batch_seed)
    torch.manual_seed(args.batch_seed)

    t0 = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_dir, local_files_only=True, trust_remote_code=False
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model_dir, local_files_only=True, trust_remote_code=False
    )
    model.eval()
    model_load_seconds = time.perf_counter() - t0

    probe_results: list[dict[str, Any]] = []
    probe_seconds: list[float] = []
    instrumentation_init_seconds = 0.0

    cases = list(probe_set["cases"])
    if args.shuffle:
        random.Random(args.batch_seed).shuffle(cases)

    for case in cases:
        seed = int(case.get("seed", args.batch_seed))
        torch.manual_seed(seed)
        prompt = render_case(tokenizer, case)
        encoded = tokenizer(prompt, return_tensors="pt")
        input_ids = encoded["input_ids"]
        attention_mask = encoded.get("attention_mask")

        case_t0 = time.perf_counter()
        with torch.no_grad():
            forward = model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                output_hidden_states=True,
                use_cache=False,
            )
            next_logits = forward.logits[0, -1, :].float()
            probs = torch.softmax(next_logits, dim=-1)
            values, indices = torch.topk(probs, k=min(args.top_k, probs.shape[-1]))
            top_tokens = [
                {
                    "token_id": int(idx.item()),
                    "token": tokenizer.decode([int(idx.item())]),
                    "probability": float(value.item()),
                }
                for value, idx in zip(values, indices)
            ]
            activation_summary = [
                {"layer": layer, **vector_summary(hidden[0, -1, :])}
                for layer, hidden in enumerate(forward.hidden_states)
            ]
            generated = model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                do_sample=False,
                max_new_tokens=args.max_new_tokens,
                use_cache=True,
            )
        elapsed = time.perf_counter() - case_t0
        probe_seconds.append(elapsed)
        new_tokens = generated[0, input_ids.shape[-1] :]
        output_text = tokenizer.decode(new_tokens, skip_special_tokens=True)

        probe_results.append(
            {
                "probe_case_id": case["probe_case_id"],
                "contrast_id": case.get("contrast_id"),
                "seed": seed,
                "render_mode": case["render"],
                "rendered_prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                "input_token_ids_sha256": sha256_bytes(
                    json.dumps(input_ids[0].tolist(), separators=(",", ":")).encode("utf-8")
                ),
                "input_token_count": int(input_ids.shape[-1]),
                "behavior": {"generated_text": output_text},
                "probability_surface": {"top_tokens": top_tokens},
                "activation_cartography": {"last_input_token": activation_summary},
                "timing": {"execution_seconds": elapsed},
                "status": "passed",
            }
        )
        del forward, generated, encoded, input_ids, attention_mask

    timing = {
        "runner_bootstrap_seconds": float(args.runner_bootstrap_seconds),
        "dependency_setup_seconds": float(args.dependency_setup_seconds),
        "artifact_hydration_seconds": float(args.artifact_hydration_seconds),
        "artifact_verification_seconds": float(args.artifact_verification_seconds),
        "model_load_seconds": model_load_seconds,
        "instrumentation_init_seconds": instrumentation_init_seconds,
        "experiment_execution_seconds": sum(probe_seconds),
    }
    timing["total_measured_seconds"] = sum(timing.values())

    package_versions = {}
    for name in ("torch", "transformers", "tokenizers", "safetensors"):
        try:
            package_versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass

    return {
        "schema_version": 1,
        "run_id": args.run_id,
        "probe_set_id": probe_set["probe_set_id"],
        "model_artifact": foundry,
        "inference": {
            "device": "cpu",
            "dtype": str(next(model.parameters()).dtype),
            "do_sample": False,
            "max_new_tokens": args.max_new_tokens,
            "batch_seed": args.batch_seed,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": package_versions,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "timing": timing,
        "batch_economics": summarize_batch_timing(timing, probe_seconds),
        "probes": probe_results,
    }


def plan(args: argparse.Namespace) -> dict[str, Any]:
    probe_set = load_probe_set(args.probes)
    return {
        "probe_set_id": probe_set["probe_set_id"],
        "case_count": len(probe_set["cases"]),
        "contrasts": sorted({c.get("contrast_id") for c in probe_set["cases"] if c.get("contrast_id")}),
        "execution_shape": "one hydrated model/runtime, sequential independent probe cases",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probes", type=Path, default=Path("experiments/mvp/probes.json"))
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--foundry-identity", type=Path)
    parser.add_argument("--run-id", default="local-unset")
    parser.add_argument("--batch-seed", type=int, default=6502632)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=32)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--runner-bootstrap-seconds", type=float, default=0.0)
    parser.add_argument("--dependency-setup-seconds", type=float, default=0.0)
    parser.add_argument("--artifact-hydration-seconds", type=float, default=0.0)
    parser.add_argument("--artifact-verification-seconds", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=Path("result.json"))
    args = parser.parse_args()

    if args.plan_only:
        result = plan(args)
    else:
        if args.model_dir is None or args.foundry_identity is None:
            parser.error("--model-dir and --foundry-identity are required unless --plan-only is used")
        result = run(args)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "mode": "plan" if args.plan_only else "run"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
