#!/usr/bin/env python3
"""Tiny real-public-CPU crossover using EXISTING R5 stream_one, not a second runner.

Only loopback Ollama with pinned model representation. Samples cgroup/host scope
as an explicitly bounded/proxy observation, never authoritative spare capacity.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import time
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "streaming"))
import streaming_probe as sp  # existing #332 measurement path

CG = Path("/sys/fs/cgroup")

def read_text(path):
    try:
        return Path(path).read_text()
    except (OSError, UnicodeError):
        return None

def key_value(path, key):
    raw = read_text(path)
    if not raw:
        return None
    for line in raw.splitlines():
        p = line.split()
        if len(p) >= 2 and p[0] == key:
            try:
                return int(p[1])
            except ValueError:
                return None
    return None

def cpu_info():
    raw = read_text(CG / "cpu.max")
    if raw:
        p = raw.split()
        if len(p) == 2 and p[0] != "max":
            try:
                quota, period = int(p[0]), int(p[1])
                if quota > 0 and period > 0:
                    return quota / period, "cgroup-v2-quota"
            except ValueError:
                pass
    try:
        count = len(os.sched_getaffinity(0))
    except AttributeError:
        count = os.cpu_count() or 1
    return float(count), "visible-cpu-proxy"

def host_memory():
    raw = read_text("/proc/meminfo")
    values = {}
    if raw:
        for line in raw.splitlines():
            parts = line.replace(":", " ").split()
            if len(parts) >= 2 and parts[0] in ("MemTotal", "MemAvailable"):
                try:
                    values[parts[0]] = int(parts[1]) * 1024
                except ValueError:
                    pass
    a, b = values.get("MemTotal"), values.get("MemAvailable")
    return (a, a - b) if a and b is not None and 0 <= b <= a else (None, None)

def memory_info():
    raw = read_text(CG / "memory.max")
    used = read_text(CG / "memory.current")
    if raw and used:
        try:
            cap, current = int(raw.strip()), int(used.strip())
            if cap > 0 and current >= 0:
                return min(current / cap, 10.), "cgroup-v2-limit"
        except ValueError:
            pass
    cap, used = host_memory()
    return ((used / cap) if cap and used is not None else None), "host-meminfo-proxy"

class HostSampler:
    def __init__(self):
        self.readings = []
        self.stop = threading.Event()
        self.thread = None
        self.capacity, self.cpu_basis = cpu_info()
        _, self.memory_basis = memory_info()

    def read(self):
        return time.monotonic(), key_value(CG / "cpu.stat", "usage_usec"), memory_info()[0]

    def loop(self):
        prior_t = prior_u = None
        while True:
            t, usec, mem = self.read()
            cpu = None
            if usec is not None and prior_u is not None and t > prior_t and self.capacity > 0:
                cpu = (usec - prior_u) / 1e6 / (t - prior_t) / self.capacity
                if not 0 <= cpu <= 100:
                    cpu = None
            self.readings.append({"cpu": round(cpu, 6) if cpu is not None else None,
                                  "memory": round(mem, 6) if mem is not None else None})
            prior_t, prior_u = t, usec
            if self.stop.wait(.35):
                break

    def __enter__(self):
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        return False

    def result(self, cell_id):
        return {"cell_id": cell_id, "sources": {"cpu": self.cpu_basis, "memory": self.memory_basis},
                "readings": self.readings}

def run_case(base, c):
    cohort = 316130 + c
    def infer(i):
        return sp.stream_one(sp.opener(), base, sp.MODEL, cohort, i, "shared")
    start = time.monotonic()
    with HostSampler() as sampler:
        if c == 1:
            samples = [infer(i) for i in range(2)]
        else:
            with ThreadPoolExecutor(max_workers=c) as pool:
                samples = list(pool.map(infer, range(2)))
        wall_ms = (time.monotonic() - start) * 1000
    cell = {"replicate": 1, "client_concurrency": c, "prefix_kind": "shared",
            "wall_ms": wall_ms, "samples": samples}
    return cell, sampler.result("r1-c%d-shared" % c)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--resources", required=True)
    args = p.parse_args()
    base = sp.origin("http://127.0.0.1:11434")
    digest = sp.digest(sp.opener(), base, sp.MODEL, sp.PIN)
    sp.stream_one(sp.opener(), base, sp.MODEL, 316130, 99, "shared")  # warm-up excluded
    trials = [run_case(base, n) for n in (1, 2)]
    receipt = {"evidence_class": "REAL_PUBLIC_CPU_STREAMING_DIRECT_INFERENCE_EXPLORATORY",
               "model": sp.MODEL, "runtime_model_digest": digest,
               "agent_task_validity": "NOT_TESTED", "kv_cache_hit_rate": "NOT_OBSERVED",
               "backend": "Ollama", "backend_version": os.environ.get("OLLAMA_VERSION", "UNKNOWN"),
               "source_sha": os.environ.get("GITHUB_SHA", "UNKNOWN"),
               "run_id": os.environ.get("GITHUB_RUN_ID", "UNKNOWN"),
               "conditions": [t[0] for t in trials]}
    resource = {"schema": "serving-phase-resource-r13/v1", "cells": [t[1] for t in trials]}
    Path(args.out).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    Path(args.resources).write_text(json.dumps(resource, indent=2, sort_keys=True) + "\n")
    print("R13_LIVE_CPU_DIRECT_MODEL_DIGEST_VERIFIED=YES CELLS=2 GPU_METRICS=UNKNOWN")

if __name__ == "__main__":
    main()
