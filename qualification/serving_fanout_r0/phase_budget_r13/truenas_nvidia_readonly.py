#!/usr/bin/env python3
"""Read-only dual NVIDIA GPU sensor adapter. No model or process mutation.

Public CI calls parse_nvidia_smi_csv() with synthetic output only.
Physical TrueNAS invocation is a separate IaC #672 HIL gate; this parser
does NOT authenticate which host/GPU it is reading or authorize admission.
"""
import argparse
import csv
import io
import json
import pathlib
import subprocess
import time

QUERY = ("nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total",
         "--format=csv,noheader,nounits")

class SensorError(ValueError):
    pass

def parse_nvidia_smi_csv(payload, expected_devices=(0, 1)):
    if not isinstance(payload, str) or len(payload) > 8192:
        raise SensorError("oversized/nontext NVIDIA sample")
    if not expected_devices or len(set(expected_devices)) != len(expected_devices):
        raise SensorError("invalid device contract")
    rows = {}
    try:
        for row in csv.reader(io.StringIO(payload)):
            if not row:
                continue
            if len(row) != 4:
                raise SensorError("wrong NVIDIA CSV column count")
            index = int(row[0].strip())
            if index not in expected_devices or index in rows:
                raise SensorError("device mismatch or duplicate index")
            values = [v.strip() for v in row[1:]]
            if any(v.upper() == "N/A" or v == "" for v in values):
                rows[index] = (None, None)
                continue
            pct, used, total = (float(v) for v in values)
            if not all(map(lambda v: v == v and abs(v) != float("inf"), (pct, used, total))):
                raise SensorError("nonfinite NVIDIA values")
            if not (0 <= pct <= 100 and 0 <= used <= total and total > 0):
                raise SensorError("out-of-bounds GPU/VRAM observation")
            rows[index] = (round(pct / 100, 6), round(used / total, 6))
    except (ValueError, OverflowError) as exc:
        raise SensorError("malformed NVIDIA CSV") from exc
    if set(rows) != set(expected_devices):
        raise SensorError("missing expected NVIDIA device")
    out = {}
    for index in expected_devices:
        load, vram = rows[index]
        out["gpu%d" % index] = load
        out["vram%d" % index] = vram
    return out

def probe_live_read_only(expected_devices=(0,1), *, run=subprocess.run):
    # Fixed argv, no shell, no arbitrary parameters or credentials.
    proc = run(QUERY, capture_output=True, text=True, timeout=3, check=False)
    if proc.returncode != 0:
        raise SensorError("nvidia-smi read unavailable (stderr not exported)")
    return parse_nvidia_smi_csv(proc.stdout, expected_devices)

def make_cell(cell_id, readings):
    if not isinstance(cell_id, str) or len(cell_id) > 80 or not cell_id.startswith("r"):
        raise SensorError("invalid cell identity")
    if not isinstance(readings, list) or not readings or len(readings) > 1000:
        raise SensorError("invalid sample count")
    for row in readings:
        if not isinstance(row, dict) or any(k not in row for k in ("gpu0","vram0","gpu1","vram1")):
            raise SensorError("missing per-device metrics")
    return {"schema": "serving-phase-resource-r13/v1", "cells": [
        {"cell_id": cell_id,
         "sources": {k: "nvidia-smi-observed" for k in ("gpu0","vram0","gpu1","vram1")},
         "readings": readings}
    ]}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", help="one synthetic 2-GPU CSV snapshot path; never runs nvidia-smi")
    p.add_argument("--live-read-only", action="store_true",
                   help="HIL-only fixed nvidia-smi query: requires separate site authorization")
    p.add_argument("--cell", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--samples", type=int, default=2)
    p.add_argument("--interval", type=float, default=1)
    args = p.parse_args()
    if bool(args.fixture) == bool(args.live_read_only):
        p.error("specify exactly one of --fixture or --live-read-only")
    if not 2 <= args.samples <= 30 or not .5 <= args.interval <= 10:
        p.error("invalid bounded collection window")
    readings = []
    for i in range(args.samples):
        if args.fixture:
            source = pathlib.Path(args.fixture).read_text()
            readings.append(parse_nvidia_smi_csv(source))
        else:
            readings.append(probe_live_read_only())
        if i + 1 < args.samples:
            time.sleep(args.interval)
    pathlib.Path(args.out).write_text(json.dumps(make_cell(args.cell, readings),
                                                  indent=2, sort_keys=True) + "\n")
    print("DUAL_GPU_RESOURCE_SAMPLES=%d GPU_CPU_TASK_GOODPUT=UNKNOWN" % len(readings))

if __name__ == "__main__":
    main()
