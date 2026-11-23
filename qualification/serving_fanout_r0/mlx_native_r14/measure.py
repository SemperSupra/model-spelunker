#!/usr/bin/env python3
"""Public small-model MLX phase measurement on hosted M1, no task qualification.

Source inspected against ml-explore/mlx-lm generate.py 1bf8da05a1ef30a3eb2e8a634180be6557fd3ca0.
No model prompt, response text, private data, or hidden reasoning is persisted.
"""
import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

MODEL_ID = "mlx-community/Qwen3-0.6B-4bit"
SOURCE_SHA = "1bf8da05a1ef30a3eb2e8a634180be6557fd3ca0"
WORDS = "amber cedar pixel vector orbit lunar".split()

class InvalidModelObservation(ValueError):
    pass

def finite_positive(v, label):
    if isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) or v <= 0:
        raise InvalidModelObservation(label + " must be a finite positive observation")
    return float(v)

def project_response(last, ttft_ms, elapsed_ms, active_memory_gb=None, cache_memory_gb=None):
    """Only native GenerationResponse metadata, never sampled text or SSE count."""
    prompt_tokens = getattr(last, "prompt_tokens", None)
    generated = getattr(last, "generation_tokens", None)
    if not isinstance(prompt_tokens, int) or isinstance(prompt_tokens, bool) or prompt_tokens < 1:
        raise InvalidModelObservation("unknown prompt token count")
    if not isinstance(generated, int) or isinstance(generated, bool) or generated < 1:
        raise InvalidModelObservation("unknown output token count")
    prefill_tps = finite_positive(getattr(last, "prompt_tps", None), "MLX prompt TPS")
    decode_tps = finite_positive(getattr(last, "generation_tps", None), "MLX generation TPS")
    ttft_ms = finite_positive(ttft_ms, "TTFT")
    elapsed_ms = finite_positive(elapsed_ms, "elapsed")
    if ttft_ms > elapsed_ms:
        raise InvalidModelObservation("impossible token chronology")
    peak_gb = finite_positive(getattr(last, "peak_memory", None), "native MLX peak memory GB")
    if getattr(last, "finish_reason", None) not in ("length", "stop"):
        raise InvalidModelObservation("generation did not end with recognized terminal marker")
    result = {
        "prompt_tokens_native": prompt_tokens,
        "output_tokens_native": generated,
        "prompt_tps_native": round(prefill_tps,3),
        "decode_tps_native": round(decode_tps,3),
        "prefill_ms_derived_from_native_tps": round(1000 * prompt_tokens / prefill_tps,3),
        "decode_ms_derived_from_native_tps": round(1000 * generated / decode_tps,3),
        "ttft_ms_client": round(ttft_ms,3),
        "elapsed_ms_client": round(elapsed_ms,3),
        "peak_mlx_memory_gb_native": round(peak_gb,6),
        "finish_reason": last.finish_reason,
    }
    for field, value in (("active_mlx_allocator_gb",active_memory_gb),
                         ("cached_mlx_allocator_gb",cache_memory_gb)):
        result[field] = round(finite_positive(value,field),6) if value is not None and value > 0 else None
    return result

def manifest(root):
    files = []
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file() or path.suffix not in (".safetensors", ".json", ".model"):
            continue
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024), b""):
                h.update(chunk)
        files.append({"path":str(path.relative_to(root)), "sha256":h.hexdigest(), "bytes":path.stat().st_size})
    if not any(f["path"].endswith(".safetensors") for f in files):
        raise InvalidModelObservation("missing immutable weight file evidence")
    canonical = json.dumps(files,sort_keys=True,separators=(",",":")).encode()
    return {"component_manifest_sha256":hashlib.sha256(canonical).hexdigest(),
            "weight_file_count":sum(f["path"].endswith(".safetensors") for f in files),
            "total_hashed_component_bytes":sum(f["bytes"] for f in files)}

def make_prompt(words_repeat):
    return ("Synthetic evaluation prompt; no tool access. " +
            " ".join(WORDS * words_repeat) +
            ". Write a single short sentence describing how to validate a software patch.")

def run_live(model_dir, revision):
    import mlx.core as mx
    from mlx_lm import load, stream_generate
    import importlib.metadata
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise InvalidModelObservation("Apple Silicon MacOS runner required")
    device = str(mx.default_device())
    if "gpu" not in device.lower():
        raise InvalidModelObservation("actual Metal GPU device not selected")
    model,tokenizer = load(str(model_dir))
    # Exclude load/warm-up from measured serving trials.
    for _ in stream_generate(model,tokenizer,make_prompt(8),max_tokens=8):
        pass
    samples = []
    for rep in (1,2):
        for repeat in (20, 70):
            started = time.monotonic()
            first = None
            last = None
            for response in stream_generate(model,tokenizer,make_prompt(repeat),max_tokens=24):
                if first is None and getattr(response,"generation_tokens",0) >= 1:
                    first = time.monotonic()
                last = response
            ended = time.monotonic()
            if last is None or first is None:
                raise InvalidModelObservation("no generated token")
            samples.append({"replicate":rep,"synthetic_repeat":repeat,**project_response(
                last,(first-started)*1000,(ended-started)*1000,
                mx.get_active_memory()/1e9,mx.get_cache_memory()/1e9)})
    return {
        "schema":"mlx-hosted-m1-phase-r14/v1",
        "evidence_class":"REAL_PUBLIC_M1_MLX_DIRECT_INFERENCE_NOT_AGENT_QUALIFICATION",
        "source_reference_sha":SOURCE_SHA,
        "mlx_lm_version":importlib.metadata.version("mlx-lm"),
        "mlx_version":importlib.metadata.version("mlx"),
        "model_id":MODEL_ID,"model_hf_revision":revision,
        "model_file_manifest":manifest(model_dir),
        "metal_device":device,
        "host_arch":platform.machine(),
        "source_sha":os.environ.get("GITHUB_SHA","UNKNOWN"),
        "gha_run_id":os.environ.get("GITHUB_RUN_ID","UNKNOWN"),
        "hosted_runner_image":os.environ.get("ImageOS","UNKNOWN"),
        "samples":samples,
        "validated_tasks_per_hour":None,
        "memory_headroom_for_surge":None,
        "hardware_equivalence_to_m2_ultra":"NOT_CLAIMED",
        "qualification_status":"HOLD_NO_INDEPENDENT_VALIDATOR_OR_RESERVE_PROOF",
    }

def fetch_snapshot(dst):
    from huggingface_hub import HfApi,snapshot_download
    info=HfApi().model_info(MODEL_ID,files_metadata=True)
    size=sum(int(f.size or 0) for f in info.siblings)
    free=shutil.disk_usage(dst.parent).free
    if not info.sha or size <=0 or size>2*1024**3 or size+2*1024**3>free:
        raise InvalidModelObservation("public model asset size/disk budget gate")
    path=snapshot_download(repo_id=MODEL_ID,revision=info.sha,local_dir=str(dst),max_workers=2)
    return Path(path), info.sha, size

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True)
    p.add_argument("--models-dir",required=True)
    args=p.parse_args()
    directory=Path(args.models_dir)
    directory.parent.mkdir(parents=True,exist_ok=True)
    path,sha,size=fetch_snapshot(directory)
    observation=run_live(path,sha)
    observation["upstream_asset_size_bytes"]=size
    Path(args.out).write_text(json.dumps(observation,indent=2,sort_keys=True)+"\n")
    print("R14_REAL_MLX_PHASES=PASS MODEL_REVISION_BOUND=YES GOODPUT=UNKNOWN")

if __name__=="__main__":
    main()
