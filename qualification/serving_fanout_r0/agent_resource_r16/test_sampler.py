import unittest
from unittest.mock import patch
from sampler import ResourceSampler,cpu_capacity,cpu_usage_usec,memory_fraction

def sampler(rows, source="cgroup-v2-quota", cap=2):
    obj=ResourceSampler(clock=lambda:0,usage=lambda:0,
                        mem=lambda:(.1,"cgroup-v2-memory-limit"),
                        capacity=lambda:(cap,source))
    obj.rows=list(rows)
    return obj

class ResourceSamplerTests(unittest.TestCase):
    def test_strong_source_observes_not_guarantees_spare(self):
        obj=sampler([(0.25,1_000_000,.20,"cgroup-v2-memory-limit"),
                     (1.25,2_500_000,.40,"cgroup-v2-memory-limit"),
                     (2.25,3_500_000,.35,"cgroup-v2-memory-limit")])
        out=obj.window(0,3)
        self.assertEqual(out["sample_count"],3)
        self.assertEqual(out["cpu_peak_fraction_of_visible_capacity"],.75)
        self.assertEqual(out["cpu_core_seconds_measured"],2.5)
        self.assertEqual(out["memory_peak_fraction_of_capacity"],.4)
        self.assertEqual(out["observed_free_fraction_min"],.25)
        self.assertEqual(out["surge_reservation_guarantee"],"NOT_ESTABLISHED")

    def test_proxy_cannot_be_promoted_to_hard_capacity(self):
        obj=sampler([(0,100000,.1,"host-memory-availability-proxy"),
                     (1,200000,.2,"host-memory-availability-proxy")],
                    source="visible-affinity-capacity-proxy")
        r=obj.window(-1,2)
        self.assertIsNone(r["observed_free_fraction_min"])
        self.assertEqual(r["observation_status"],"OBSERVED_PROXY_NOT_RESERVE_PROOF")

    def test_unknown_vs_true_zero(self):
        missing=sampler([(0,None,.1,"cgroup-v2-memory-limit"),
                         (1,None,.1,"cgroup-v2-memory-limit")])
        x=missing.window(-1,2)
        self.assertIsNone(x["cpu_peak_fraction_of_visible_capacity"])
        self.assertEqual(x["observation_status"],"UNKNOWN_INSUFFICIENT_SAMPLES")
        zero=sampler([(0,1_000_000,.0,"cgroup-v2-memory-limit"),
                      (1,1_000_000,.0,"cgroup-v2-memory-limit")])
        z=zero.window(-1,2)
        self.assertEqual(z["cpu_peak_fraction_of_visible_capacity"],0)
        self.assertEqual(z["memory_peak_fraction_of_capacity"],0)
        self.assertEqual(z["observed_free_fraction_min"],1)

    def test_weak_mixed_source_denies_reserve(self):
        s=sampler([(0,1_000_000,.2,"cgroup-v2-memory-limit"),
                   (1,2_000_000,.5,"host-memory-availability-proxy")])
        self.assertEqual(s.window(-1,2)["observation_status"],"OBSERVED_PROXY_NOT_RESERVE_PROOF")

    def test_counter_reset_not_negative_usage(self):
        s=sampler([(0,2_000_000,.3,"cgroup-v2-memory-limit"),
                   (1,1_000_000,.3,"cgroup-v2-memory-limit")])
        x=s.window(-1,2)
        self.assertIsNone(x["cpu_peak_fraction_of_visible_capacity"])
        self.assertIsNone(x["observed_free_fraction_min"])

    def test_missing_sample_and_invalid_window(self):
        s=sampler([(0.1,100,.1,"cgroup-v2-memory-limit")])
        self.assertEqual(s.window(0,1)["sample_count"],1)
        self.assertEqual(s.window(0,1)["observation_status"],"UNKNOWN_INSUFFICIENT_SAMPLES")
        with self.assertRaises(ValueError):
            s.window(1,1)

    def test_cgroup_quota_and_usage(self):
        def fake(path):
            p=str(path)
            if p.endswith("cpu.max"):return "200000 100000"
            if p.endswith("cpu.stat"):return "nr_periods 2\nusage_usec 123456\n"
        with patch("sampler.read",side_effect=fake):
            self.assertEqual(cpu_capacity(),(2,"cgroup-v2-quota"))
            self.assertEqual(cpu_usage_usec(),123456)

    def test_cgroup_memory_source(self):
        def fake(path):
            p=str(path)
            if p.endswith("memory.max"):return "1000"
            if p.endswith("memory.current"):return "250"
        with patch("sampler.read",side_effect=fake):
            self.assertEqual(memory_fraction(),(.25,"cgroup-v2-memory-limit"))

    def test_bounded_window_and_sampling_interval(self):
        with self.assertRaises(ValueError):
            ResourceSampler(interval_seconds=.001)
        s=ResourceSampler(interval_seconds=.1)
        s.start()
        try:
            import time
            time.sleep(.22)
            r=s.window(0,time.monotonic()+1)
            self.assertGreaterEqual(r["sample_count"],2)
        finally:
            s.stop()

if __name__=="__main__":
    unittest.main()
