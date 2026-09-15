#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import torch


def dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob('*'):
        try:
            if p.is_file():
                total += p.stat().st_size
        except FileNotFoundError:
            pass
    return total


def pkg(name: str) -> str:
    return importlib.metadata.version(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--started-ns-file', type=Path, required=True)
    ap.add_argument('--cache-hit', default='')
    ap.add_argument('--cache-key', required=True)
    ap.add_argument('--venv', type=Path, required=True)
    ap.add_argument('--output', type=Path, default=Path('out/runtime-venv-metrics.json'))
    args = ap.parse_args()

    # Functional smoke is deliberately integer-exact so cross-runner floating
    # reduction kernels cannot create false environment-drift alarms.
    x = torch.arange(1, 257, dtype=torch.int64).reshape(16, 16)
    y = (x * 17 + 23) ^ (x.T * 3)
    integer_checksum = hashlib.sha256(y.numpy().tobytes()).hexdigest()

    freeze = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True)
    freeze_hash = hashlib.sha256(freeze.encode('utf-8')).hexdigest()
    ended_ns = time.time_ns()

    payload = {
        'schema_version': 1,
        'run_id': os.environ.get('GITHUB_RUN_ID'),
        'code_revision': os.environ.get('GITHUB_SHA'),
        'cache_hit': str(args.cache_hit).lower() == 'true',
        'cache_hit_raw': args.cache_hit,
        'cache_key': args.cache_key,
        'restore_or_build_to_ready_seconds': (ended_ns - int(args.started_ns_file.read_text().strip())) / 1e9,
        'venv_size_bytes': dir_size_bytes(args.venv),
        'runtime': {
            'python': platform.python_version(),
            'python_cache_tag': sys.implementation.cache_tag,
            'python_executable': sys.executable,
            'platform': platform.platform(),
            'machine': platform.machine(),
            'torch': torch.__version__,
            'transformers': pkg('transformers'),
            'huggingface_hub': pkg('huggingface-hub'),
            'safetensors': pkg('safetensors'),
            'jsonschema': pkg('jsonschema'),
        },
        'pip_freeze_sha256': 'sha256:' + freeze_hash,
        'integer_torch_smoke_sha256': 'sha256:' + integer_checksum,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
