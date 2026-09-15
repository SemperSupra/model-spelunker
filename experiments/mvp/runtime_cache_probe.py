#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import torch
import transformers
import huggingface_hub
import safetensors
import jsonschema


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--started-ns-file', type=Path, required=True)
    ap.add_argument('--cache-hit', default='')
    ap.add_argument('--cache-key', required=True)
    ap.add_argument('--output', type=Path, default=Path('out/runtime-cache-metrics.json'))
    args = ap.parse_args()

    started_ns = int(args.started_ns_file.read_text().strip())
    ended_ns = time.time_ns()
    cache_dir = Path.home() / '.cache' / 'pip'

    torch.manual_seed(12345)
    a = torch.arange(1, 65, dtype=torch.float32).reshape(8, 8)
    b = torch.linspace(-1.0, 1.0, 64, dtype=torch.float32).reshape(8, 8)
    c = torch.softmax(a @ b, dim=-1)
    checksum = hashlib.sha256(c.numpy().tobytes()).hexdigest()

    freeze = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True)
    freeze_hash = hashlib.sha256(freeze.encode('utf-8')).hexdigest()

    payload = {
        'schema_version': 1,
        'run_id': os.environ.get('GITHUB_RUN_ID'),
        'code_revision': os.environ.get('GITHUB_SHA'),
        'cache_hit': str(args.cache_hit).lower() == 'true',
        'cache_hit_raw': args.cache_hit,
        'cache_key': args.cache_key,
        'setup_restore_install_seconds': (ended_ns - started_ns) / 1e9,
        'pip_cache_size_bytes': dir_size_bytes(cache_dir),
        'runtime': {
            'python': platform.python_version(),
            'python_cache_tag': sys.implementation.cache_tag,
            'platform': platform.platform(),
            'machine': platform.machine(),
            'torch': torch.__version__,
            'transformers': transformers.__version__,
            'huggingface_hub': huggingface_hub.__version__,
            'safetensors': safetensors.__version__,
            'jsonschema': jsonschema.__version__,
        },
        'pip_freeze_sha256': 'sha256:' + freeze_hash,
        'torch_smoke_sha256': 'sha256:' + checksum,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
