import subprocess
import unittest
from unittest.mock import Mock
from truenas_nvidia_readonly import (QUERY, SensorError, parse_nvidia_smi_csv,
                                     probe_live_read_only, make_cell)

VALID = "0, 75, 18000, 24564\n1, 20, 1000, 24564\n"

class NvidiaReadOnlyTests(unittest.TestCase):
    def test_two_distinct_devices_never_aggregate(self):
        result = parse_nvidia_smi_csv(VALID)
        self.assertEqual(result["gpu0"], .75)
        self.assertEqual(result["gpu1"], .2)
        self.assertTrue(result["vram0"] > result["vram1"])

    def test_unknown_is_none_not_zero(self):
        result = parse_nvidia_smi_csv("0, N/A, N/A, N/A\n1, 0, 0, 24564\n")
        self.assertIsNone(result["gpu0"])
        self.assertIsNone(result["vram0"])
        self.assertEqual(result["gpu1"], 0)
        self.assertEqual(result["vram1"], 0)

    def test_errors_not_silent_partial_success(self):
        bad = [
            "0, 50, 100, 24564\n",
            "0, 50, 100, 24564\n0, 10, 200, 24564\n",
            "0, 50, 100, 24564\n2, 10, 200, 24564\n",
            "0, 101, 100, 24564\n1, 10, 200, 24564\n",
            "0, 50, 24999, 24564\n1, 10, 200, 24564\n",
            "0, 50, -1, 24564\n1, 10, 200, 24564\n",
            "0, nan, 100, 24564\n1, 10, 200, 24564\n",
            "0, 10, 100, 24564,EXTRA\n1, 10, 200, 24564\n",
        ]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(SensorError):
                parse_nvidia_smi_csv(raw)

    def test_fixed_nvidia_smi_argv_and_no_mutation(self):
        runner = Mock(return_value=subprocess.CompletedProcess(QUERY, 0, VALID, ""))
        row = probe_live_read_only(run=runner)
        self.assertEqual(row["gpu0"], .75)
        args, kwargs = runner.call_args
        self.assertEqual(args[0], QUERY)
        self.assertNotIn("shell", kwargs)
        self.assertLessEqual(kwargs["timeout"], 3)
        self.assertFalse(any(a.startswith("--gpu-reset") for a in args[0]))

    def test_command_error_does_not_log_stderr(self):
        runner = Mock(return_value=subprocess.CompletedProcess(QUERY, 1, "", "private host detail"))
        with self.assertRaisesRegex(SensorError, "read unavailable"):
            probe_live_read_only(run=runner)

    def test_resource_cell_requires_both_devices(self):
        rows = [parse_nvidia_smi_csv(VALID)] * 2
        obj = make_cell("r1-c2-shared", rows)
        self.assertEqual(obj["cells"][0]["sources"]["gpu1"], "nvidia-smi-observed")
        with self.assertRaises(SensorError):
            make_cell("r1-c2-shared", [{"gpu0": .75}])

if __name__ == "__main__":
    unittest.main()
