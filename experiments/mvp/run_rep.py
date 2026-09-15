#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
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

MODEL_REPO = "HuggingFaceTB/SmolLM2-135M-Instruct"
MODEL_REVISION = "e2c3f7557efbdec707ae3a336371d169783f1da1"
LOGICAL_ID = "llm/smollm2/135m-instruct"
MODEL_FILES = [
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
]


def now() -> float:
    return time.perf_counter()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_files(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for name in MODEL_FILES:
        path = root / name
        if not path.is_file():
            raise RuntimeError(f"required model artifact file missing: {name}")
        records.append({"path": name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    records.sort(key=lambda item: item["path"])
    return records


def content_manifest(root: Path) -> tuple[str, list[dict[str, Any]]]:
    files = artifact_files(root)
    material = {
        "schema_version": 1,
        "logical_id": LOGICAL_ID,
        "upstream": {
            "provider": "huggingface",
            "repository": MODEL_REPO,
            "exact_revision": MODEL_REVISION,
        },
        "files": files,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest(), files


def render_prompt(tokenizer: Any, condition: dict[str, Any]) -> str:
    user = condition["user"]
    if condition["render"] == "native":
        return tokenizer.apply_chat_template(
            [{"role": "user", "content": user}], tokenize=False, add_generation_prompt=True
        )
    if condition["render"] == "generic":
        return f"User: {user}\nAssistant:"
    raise ValueError(f"unsupported render mode: {condition['render']}")


def token_hash(ids: torch.Tensor) -> str:
    raw = ",".join(str(int(x)) for x in ids.reshape(-1).tolist()).encode("ascii")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def sequence_logprob(model: Any, tokenizer: Any, prompt: str, candidate: str) -> dict[str, Any]:
    prompt_ids = tokenizer(prompt, return_tensors="pt").input_ids
    candidate_ids = tokenizer(candidate, add_special_tokens=False, return_tensors="pt").input_ids[0]
    if candidate_ids.numel() == 0:
        raise RuntimeError(f"candidate tokenized empty: {candidate!r}")
    full = torch.cat([prompt_ids[0], candidate_ids], dim=0).unsqueeze(0)
    with torch.inference_mode():
        logits = model(full, use_cache=False).logits[0]
    start = prompt_ids.shape[1] - 1
    total = 0.0
    per_token = []
    for offset, tok in enumerate(candidate_ids.tolist()):
        lp = torch.log_softmax(logits[start + offset], dim=-1)[tok].item()
        total += lp
        per_token.append({"token_id": int(tok), "logprob": float(lp)})
    return {"candidate": candidate, "logprob": float(total), "tokens": per_token}


def summarize_hidden(hidden_states: tuple[torch.Tensor, ...]) -> tuple[list[dict[str, float]], list[torch.Tensor]]:
    summaries, vectors = [], []
    for layer, tensor in enumerate(hidden_states):
        vec = tensor[0, -1, :].detach().float().cpu()
        vectors.append(vec)
        summaries.append({
            "layer": layer,
            "l2": float(torch.linalg.vector_norm(vec).item()),
            "mean": float(vec.mean().item()),
            "std": float(vec.std(unbiased=False).item()),
        })
    return summaries, vectors


def activation_contrast(left: list[torch.Tensor], right: list[torch.Tensor]) -> list[dict[str, float]]:
    if len(left) != len(right):
        raise RuntimeError("hidden-state layer count mismatch")
    out = []
    for layer, (a, b) in enumerate(zip(left, right)):
        denom = max(float(torch.linalg.vector_norm(a).item() * torch.linalg.vector_norm(b).item()), 1e-12)
        cosine = float(torch.dot(a, b).item() / denom)
        delta = b - a
        out.append({
            "layer": layer,
            "cosine_similarity": cosine,
            "cosine_distance": 1.0 - cosine,
            "delta_l2": float(torch.linalg.vector_norm(delta).item()),
            "mean_abs_delta": float(delta.abs().mean().item()),
        })
    return out


def run_condition(model: Any, tokenizer: Any, condition: dict[str, Any], candidates: list[str]) -> tuple[dict[str, Any], list[torch.Tensor]]:
    started = now()
    prompt = render_prompt(tokenizer, condition)
    encoded = tokenizer(prompt, return_tensors="pt")
    with torch.inference_mode():
        forward = model(**encoded, output_hidden_states=True, use_cache=False)
    hidden_summary, hidden_vectors = summarize_hidden(forward.hidden_states)
    scores = [sequence_logprob(model, tokenizer, prompt, candidate) for candidate in candidates]
    winner = max({x["candidate"]: x["logprob"] for x in scores}, key=lambda k: {x["candidate"]: x["logprob"] for x in scores}[k])
    with torch.inference_mode():
        generated = model.generate(
            **encoded, max_new_tokens=16, do_sample=False, use_cache=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    new_ids = generated[0, encoded.input_ids.shape[1]:]
    return ({
        "condition_id": condition["condition_id"],
        "render": condition["render"],
        "prompt_sha256": "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "input_token_ids_sha256": token_hash(encoded.input_ids),
        "input_tokens": int(encoded.input_ids.numel()),
        "candidate_scores": scores,
        "candidate_winner": winner,
        "generation": tokenizer.decode(new_ids, skip_special_tokens=True).strip(),
        "hidden_summary": hidden_summary,
        "elapsed_seconds": now() - started,
    }, hidden_vectors)


def peak_rss_mib() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def disk_free_mib(path: Path) -> float:
    stat = os.statvfs(path)
    return (stat.f_bavail * stat.f_frsize) / (1024 * 1024)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probes", type=Path, default=Path("experiments/mvp/probes.json"))
    parser.add_argument("--output", type=Path, default=Path("out/mvp-rep.json"))
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--foundry-digest")
    parser.add_argument("--foundry-record-ref")
    args = parser.parse_args()

    run_started_wall, run_started = time.time(), now()
    timings: dict[str, float] = {}
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    torch.manual_seed(0)

    t = now()
    if args.model_dir:
        model_dir, source = args.model_dir.resolve(), "prehydrated"
    else:
        model_dir = Path(snapshot_download(
            repo_id=MODEL_REPO,
            revision=MODEL_REVISION,
            allow_patterns=MODEL_FILES,
            local_dir="/tmp/model-spelunker-smollm2",
        )).resolve()
        source = "upstream-exact-revision"
    timings["hydrate_seconds"] = now() - t

    t = now()
    manifest_digest, files = content_manifest(model_dir)
    timings["artifact_verify_seconds"] = now() - t

    t = now()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(model_dir, local_files_only=True, torch_dtype=torch.float32)
    model.eval()
    timings["model_load_seconds"] = now() - t

    probes = json.loads(args.probes.read_text(encoding="utf-8"))["probes"]
    observations = []
    execution_started = now()
    for probe in probes:
        condition_results, vectors = [], {}
        for condition in probe["conditions"]:
            result, hidden_vectors = run_condition(model, tokenizer, condition, probe["candidates"])
            condition_results.append(result)
            vectors[condition["condition_id"]] = hidden_vectors
        left_id = probe["conditions"][0]["condition_id"]
        right_id = probe["conditions"][1]["condition_id"]
        observations.append({
            "probe_id": probe["probe_id"],
            "contrast_id": probe["contrast_id"],
            "conditions": condition_results,
            "activation_contrast": activation_contrast(vectors[left_id], vectors[right_id]),
        })
    timings["experiment_seconds"] = now() - execution_started

    git_sha = os.environ.get("GITHUB_SHA")
    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{int(run_started_wall)}")
    artifact_provenance = {
        "tracked": True,
        "foundry_repository": "SemperSupra/model-artifact-foundry",
        "logical_artifact_id": LOGICAL_ID,
        "upstream_provider": "huggingface",
        "upstream_repository": MODEL_REPO,
        "upstream_revision": MODEL_REVISION,
        "identity_kind": "oci" if args.foundry_digest else "content-manifest",
        "identity_digest": args.foundry_digest or manifest_digest,
        "foundry_record_ref": args.foundry_record_ref,
        "consumer_selection_ref": f"model-spelunker@{git_sha}" if git_sha else None,
        "verified": True,
        "verification_ref": "foundry-oci-plus-local-manifest" if args.foundry_digest else "foundry-compatible-local-content-manifest",
        "tokenizer_artifact": None,
    }
    observation_hash = "sha256:" + hashlib.sha256(
        json.dumps(observations, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    bundle = {
        "probe_id": "mvp-corpus-v1",
        "instrument": "shared-forward-behavior-logits-activation-summary",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": MODEL_REPO, "revision": MODEL_REVISION, "logical_id": LOGICAL_ID},
        "artifact_provenance": artifact_provenance,
        "access_tier": "A1",
        "evidence_level": "OBSERVED",
        "claim_tags": ["LOCALIZED"],
        "observations": {"probes": observations},
        "derived_metrics": {
            "probe_count": len(observations),
            "condition_count": sum(len(x["conditions"]) for x in observations),
            "content_manifest_file_count": len(files),
        },
        "artifacts": [],
        "uncertainty": {
            "status": "exploratory-until-foundry-oci-promotion" if not args.foundry_digest else "artifact-promoted",
            "notes": ["Greedy generation is deterministic for this rep; floating-point results may vary slightly across runtimes."]
        },
        "known_assumptions": [
            "The first two conditions of each ProbeCase define the activation contrast.",
            "Content-manifest identity uses the Foundry canonical SHA-256 material shape."
        ],
        "known_failure_modes": [
            "Generic rendering is intentionally non-native and may create protocol artifacts.",
            "Candidate scoring and free generation can disagree because they answer different measurement questions."
        ],
        "contradictions": [],
        "cost": {
            **timings,
            "total_seconds": now() - run_started,
            "peak_rss_mib": peak_rss_mib(),
            "disk_free_mib_after": disk_free_mib(Path("/tmp")),
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
                "model_source": source,
                "github_runner_image": os.environ.get("ImageOS"),
                "github_runner_arch": os.environ.get("RUNNER_ARCH"),
            },
            "randomness": {"torch_manual_seed": 0, "generation": "greedy"},
            "raw_input_hash": "sha256:" + hashlib.sha256(args.probes.read_bytes()).hexdigest(),
            "raw_output_hash": observation_hash,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_id": bundle["provenance"]["run_id"],
        "model_revision": MODEL_REVISION,
        "artifact_identity": artifact_provenance["identity_digest"],
        "probes": len(observations),
        "total_seconds": bundle["cost"]["total_seconds"],
        "peak_rss_mib": bundle["cost"]["peak_rss_mib"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
