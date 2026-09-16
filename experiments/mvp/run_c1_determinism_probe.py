#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

import jax

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_c1_learned_reverse as base  # noqa: E402


def cpu_model() -> str:
    try:
        for line in Path('/proc/cpuinfo').read_text(errors='ignore').splitlines():
            if line.lower().startswith('model name'):
                return line.split(':', 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or 'unknown'


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); ap.add_argument('--mode',choices=['default','reduced-threading'],required=True); args=ap.parse_args()
    base.SEED=0; split=base.make_split(); t=time.perf_counter()
    params,_=base.train_once(split,capture=False)
    seconds=time.perf_counter()-t; digest,count=base.params_hash(params)
    train=base.accuracy(params,split['train_x'],split['train_y']); test=base.accuracy(params,split['test_x'],split['test_y']); allm=base.accuracy(params,split['all_x'],split['all_y'])
    row={
        'mode':args.mode,
        'seed':0,
        'parameter_sha256':digest,
        'parameter_count':count,
        'train_sequence_accuracy':train['sequence_accuracy'],
        'test_sequence_accuracy':test['sequence_accuracy'],
        'all_sequence_accuracy':allm['sequence_accuracy'],
        'training_seconds':seconds,
        'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.0,
        'environment':{
            'python':platform.python_version(),
            'jax':jax.__version__,
            'backend':jax.default_backend(),
            'devices':[str(x) for x in jax.devices()],
            'cpu_model':cpu_model(),
            'runner_name':os.environ.get('RUNNER_NAME'),
            'runner_os':os.environ.get('RUNNER_OS'),
            'runner_arch':os.environ.get('RUNNER_ARCH'),
            'xla_flags':os.environ.get('XLA_FLAGS',''),
            'omp_num_threads':os.environ.get('OMP_NUM_THREADS'),
            'openblas_num_threads':os.environ.get('OPENBLAS_NUM_THREADS'),
            'mkl_num_threads':os.environ.get('MKL_NUM_THREADS'),
        },
    }
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(row,indent=2,sort_keys=True)+'\n')
    print(json.dumps(row,sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
