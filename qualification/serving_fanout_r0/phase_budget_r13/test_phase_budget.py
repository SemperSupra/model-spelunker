#!/usr/bin/env python3
"""Deterministic RED/BLUE cases for the R13 phase and resource reducer."""
import copy
import unittest
from phase_budget import InvalidReceipt, reduce

DIGEST = "a" * 64

def fixture():
    def sample(i):
        return {"index": i, "ttft_ms": 90 + i, "elapsed_ms": 310 + i,
                "prompt_tokens": 160, "output_tokens": 16,
                "prefill_ms": 80, "decode_ms": 200, "load_ms": 0}
    return {
        "evidence_class": "REAL_PUBLIC_CPU_STREAMING_DIRECT_INFERENCE_EXPLORATORY",
        "runtime_model_digest": DIGEST,
        "agent_task_validity": "NOT_TESTED",
        "conditions": [
            {"replicate": 1, "client_concurrency": n, "prefix_kind": "shared",
             "wall_ms": 750 if n == 1 else 400,
             "samples": [sample(0), sample(1)]}
            for n in (1, 2)
        ],
    }

def resources(source="cgroup-v2-quota", include_memory=True):
    sources = {"cpu": source}
    if include_memory:
        sources["memory"] = "cgroup-v2-limit"
    return {
        "schema": "serving-phase-resource-r13/v1",
        "cells": [
            {"cell_id": "r1-c%d-shared" % n, "sources": sources,
             "readings": [
                 {"cpu": .47, "memory": .25 if include_memory else None},
                 {"cpu": .65, "memory": .34 if include_memory else None},
             ]}
            for n in (1, 2)
        ],
    }

class PhaseTests(unittest.TestCase):
    def test_blue_phase_sums_not_wall_tokens(self):
        x = reduce(fixture(), resources())
        self.assertEqual(x["goodput_verified_tasks_per_hour"], None)
        self.assertEqual(x["goodput_verification"], "NOT_MEASURED_REQUIRES_EXISTING_139_INDEPENDENT_VALIDATOR")
        self.assertEqual(x["cells"][0]["prefill_tps_engine_sum_ratio"], 2000)
        self.assertEqual(x["cells"][0]["decode_tps_engine_sum_ratio"], 80)
        self.assertEqual(x["cells"][0]["resource_headroom"]["status"], "OBSERVED_BOUNDED_NOT_SURGE_GUARANTEED")
        self.assertTrue(x["cells"][0]["resource_headroom"]["resource_threshold_met"])
        self.assertFalse(x["cells"][0]["route_qualified"])

    def test_unknown_when_no_samples(self):
        x = reduce(fixture())
        self.assertIsNone(x["cells"][0]["goodput_verified_tasks_per_hour"])
        self.assertEqual(x["cells"][0]["resource_headroom"]["status"], "UNKNOWN_NO_HOST_OBSERVATIONS")

    def test_zero_duration_is_unknown_rate_not_zero_throughput(self):
        r = fixture()
        for s in r["conditions"][0]["samples"]:
            s["prefill_ms"] = 0
        x = reduce(r)
        self.assertIsNone(x["cells"][0]["prefill_tps_engine_sum_ratio"])

    def test_weak_cpu_capacity_never_called_measured_bound(self):
        x = reduce(fixture(), resources(source="visible-cpu-proxy"))
        self.assertEqual(x["cells"][0]["resource_headroom"]["status"], "OBSERVED_PROXY_ONLY")
        self.assertIn("cpu", x["cells"][0]["resource_headroom"]["weak_capacity_sources"])

    def test_memory_sensor_absent_is_unknown(self):
        x = reduce(fixture(), resources(include_memory=False))
        self.assertEqual(x["cells"][0]["resource_headroom"]["status"], "UNKNOWN_INCOMPLETE_RESOURCE_COVERAGE")
        self.assertIn("memory", x["cells"][0]["resource_headroom"]["missing"])

    def test_dual_a5000_requires_each_gpu_and_vram(self):
        x = reduce(fixture(), resources(), required=("cpu","memory","gpu0","vram0","gpu1","vram1"))
        self.assertEqual(x["cells"][0]["resource_headroom"]["status"], "UNKNOWN_INCOMPLETE_RESOURCE_COVERAGE")
        for k in ("gpu0","vram0","gpu1","vram1"):
            self.assertIn(k, x["cells"][0]["resource_headroom"]["missing"])

    def test_dual_a5000_single_gpu_exhausted_fails(self):
        r = resources()
        for c in r["cells"]:
            c["sources"].update({"gpu0":"nvml-observed", "gpu1":"nvml-observed",
                                 "vram0":"nvml-observed", "vram1":"nvml-observed"})
            for reading in c["readings"]:
                reading.update({"gpu0":.25,"gpu1":.9,"vram0":.4,"vram1":.6})
        x = reduce(fixture(), r, required=("gpu0","vram0","gpu1","vram1"), reserve=.25)
        self.assertFalse(x["cells"][0]["resource_headroom"]["resource_threshold_met"])
        self.assertEqual(x["cells"][0]["resource_headroom"]["peak_fraction"]["gpu1"], .9)

    def test_unvalidated_fast_inference_never_promotes(self):
        r = fixture()
        for c in r["conditions"]:
            for s in c["samples"]:
                s["ttft_ms"] = 1
                s["elapsed_ms"] = 2
        x = reduce(r, resources())
        self.assertTrue(all(c["interactive_ttft_slo_met"] for c in x["cells"]))
        self.assertTrue(all(not c["route_qualified"] for c in x["cells"]))

    def test_negative_controls_reject_invalid_receipts(self):
        r = fixture()
        treatments = []
        def modified(fn):
            v = copy.deepcopy(r)
            fn(v)
            treatments.append(v)
        modified(lambda v: v.update(runtime_model_digest="alias-not-a-digest"))
        modified(lambda v: v.update(evidence_class="SYNTHETIC_SIMULATION_NOT_HARDWARE"))
        modified(lambda v: v.update(agent_task_validity="PASS"))
        modified(lambda v: v["conditions"].append(copy.deepcopy(v["conditions"][0])))
        modified(lambda v: v["conditions"][0]["samples"][0].update(ttft_ms=9999))
        modified(lambda v: v["conditions"][0]["samples"][0].update(prompt_tokens=False))
        modified(lambda v: v["conditions"][0]["samples"][0].update(decode_ms=-1))
        modified(lambda v: v["conditions"][0]["samples"][0].update(prefill_ms=float("nan")))
        modified(lambda v: v["conditions"][0].update(client_concurrency=99))
        for v in treatments:
            with self.subTest(case=treatments.index(v)), self.assertRaises(InvalidReceipt):
                reduce(v)

    def test_negative_resource_falsification(self):
        for bad in (lambda r:r["cells"][0]["readings"][0].update(cpu=float("inf")),
                    lambda r:r["cells"][0]["sources"].update(cpu="unsupported-private-metric"),
                    lambda r:r["cells"].append(copy.deepcopy(r["cells"][0])),
                    lambda r:r["cells"][0].update(sources=[]),
                    lambda r:r["cells"][0].update(cell_id="forged-unmatched")):
            r = resources()
            bad(r)
            with self.assertRaises(InvalidReceipt):
                reduce(fixture(), r)

    def test_invalid_policy(self):
        for kw in ({"reserve":0}, {"reserve":float("nan")},
                   {"required":("gpu0","gpu0")}, {"required":("other",)},
                   {"ttft_slo_ms":-1}):
            with self.assertRaises(InvalidReceipt):
                reduce(fixture(), **kw)

if __name__ == "__main__":
    unittest.main()
