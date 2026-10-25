"""Reference CPU numeric controls for reproducible Model Spelunker measurements."""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path
from typing import Any

# Set thread-related environment before importing torch. The experiment favors
# reproducibility over throughput for its reference measurements.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["TORCH_NUM_THREADS"] = "1"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import torch

NUMERIC_MODE = "reference-fp64-single-thread-no-mkldnn-v0.1"


def configure_reference_cpu(seed: int) -> None:
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        # Safe when a caller imported another torch component that initialized
        # the inter-op pool first. The runtime fingerprint makes this visible.
        pass
    torch.backends.mkldnn.enabled = False
    torch.use_deterministic_algorithms(True)


def prepare_reference_model(model: Any) -> Any:
    model.eval()
    model.to(device="cpu", dtype=torch.float64)
    return model


def _cpu_model_name() -> str | None:
    path = Path("/proc/cpuinfo")
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^model name\s*:\s*(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def runtime_fingerprint() -> dict[str, Any]:
    return {
        "numeric_mode": NUMERIC_MODE,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_model": _cpu_model_name(),
        "torch_version": torch.__version__,
        "torch_num_threads": torch.get_num_threads(),
        "torch_num_interop_threads": torch.get_num_interop_threads(),
        "mkldnn_enabled": torch.backends.mkldnn.enabled,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "default_dtype": str(torch.get_default_dtype()),
        "model_dtype": "torch.float64",
    }
