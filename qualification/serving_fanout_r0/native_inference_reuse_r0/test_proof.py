"""Independent corruptions of the fixed-case admission and result joins."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from qualification.serving_fanout_r0.native_inference_reuse_r0 import proof as p


class FixedInferenceControls(unittest.TestCase):
    def test_model_identity_controls(self):
        layer = {"mediaType": "application/vnd.ollama.image.model", "digest": p.MODEL_BLOB,
                 "size": p.MODEL_BYTES}
        args = [{"layers": [layer]}, p.MODEL_MANIFEST, p.MODEL_BLOB, p.MODEL_BYTES, b"GGUF"]
        self.assertEqual(p.model_contract(*args)["blob_sha256"], p.MODEL_BLOB)
        changes = [(1, "sha256:" + "0" * 64), (2, "sha256:" + "1" * 64),
                   (3, p.MODEL_BYTES - 1), (4, b"html"),
                   (0, {"layers": [layer, layer]}),
                   (0, {"layers": [dict(layer, size=True)]}),
                   (0, {"layers": [dict(layer, digest="sha256:" + "2" * 64)]})]
        for index, replacement in changes:
            with self.subTest(index=index, replacement=replacement):
                changed = copy.deepcopy(args)
                changed[index] = replacement
                with self.assertRaises(ValueError):
                    p.model_contract(*changed)

    def test_external_oracle_rejects_wrong_and_missing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            output = snapshot / "value.txt"
            def record(present):
                p.write(snapshot / "snapshot_manifest.json", {"files": {"value.txt": {
                    "present": present, "size_bytes": output.stat().st_size if present else 0,
                    "sha256": p.sha(output) if present else None}}})
            output.write_bytes(b"READY\n")
            record(True)
            self.assertEqual(p.snapshot_check(root)["exit_code"], 0)
            output.write_bytes(b"not the required final state\n")
            record(True)
            with self.assertRaisesRegex(ValueError, "independent_snapshot_oracle"):
                p.snapshot_check(root)
            output.unlink()
            record(False)
            with self.assertRaisesRegex(ValueError, "snapshot_presence"):
                p.snapshot_check(root)

    def test_snapshot_integrity_precedes_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            (snapshot / "value.txt").write_bytes(b"READY\n")
            p.write(snapshot / "snapshot_manifest.json", {"files": {"value.txt": {
                "present": True, "size_bytes": 6, "sha256": "sha256:" + "0" * 64}}})
            with self.assertRaisesRegex(ValueError, "snapshot_digest"):
                p.snapshot_check(root)

    def pair(self):
        producer = {"status": "ACCEPTED_FIXED_CASE", "role": "producer",
                    "identity": {"source_commit": "a" * 40, "run_id": "1", "run_attempt": "1"},
                    "source": {"commit": "a" * 40, "tree": "b" * 40}, "model": {"blob": p.MODEL_BLOB},
                    "harness": p.HARNESS, "native_manifest_sha256": "sha256:" + "a" * 64,
                    "server_binary_sha256": "sha256:" + "b" * 64, "server_revision": p.reuse.REV,
                    "server_flags": p.SERVER_FLAGS, "task_package_digest": "sha256:" + "c" * 64,
                    "settings": p.SETTINGS, "timeouts": p.TIMEOUTS,
                    "chat_template_sha256": "sha256:" + "d" * 64,
                    "chat_template_tool_use_sha256": None,
                    "observed_server_configuration": {"context_per_slot": 8192, "slots": 1, "alias": p.ALIAS},
                    "snapshot": {"output_sha256": "sha256:" + "e" * 64},
                    "teardown": {"process_stopped": True, "forced_kill": False,
                                 "running_before_owned_shutdown": True}}
        consumer = copy.deepcopy(producer)
        consumer["role"] = "consumer"
        return producer, consumer

    def test_pair_rejects_each_identity_configuration_and_deadline_drift(self):
        producer, consumer = self.pair()
        self.assertEqual(p.compare_fixed_case(producer, consumer)["cases_per_side"], 1)
        for field in ("identity", "source", "model", "harness", "native_manifest_sha256",
                      "server_binary_sha256", "server_revision", "server_flags", "task_package_digest",
                      "settings", "timeouts", "chat_template_sha256", "chat_template_tool_use_sha256",
                      "observed_server_configuration", "status", "role"):
            with self.subTest(field=field):
                changed = copy.deepcopy(consumer)
                changed[field] = "wrong"
                with self.assertRaises(ValueError):
                    p.compare_fixed_case(producer, changed)

    def test_pair_rejects_incomplete_teardown_and_output_drift(self):
        producer, consumer = self.pair()
        for field, value in (("process_stopped", False), ("forced_kill", True),
                             ("running_before_owned_shutdown", False)):
            changed = copy.deepcopy(consumer)
            changed["teardown"][field] = value
            with self.assertRaisesRegex(ValueError, "pair_teardown"):
                p.compare_fixed_case(producer, changed)
        consumer["snapshot"]["output_sha256"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "pair_output"):
            p.compare_fixed_case(producer, consumer)
        crashed = SimpleNamespace(poll=lambda: -11, returncode=-11)
        observed = p.stop_process(crashed)
        self.assertFalse(observed["running_before_owned_shutdown"])
        self.assertEqual(observed["exit_code"], -11)
        producer, consumer = self.pair()
        consumer["teardown"] = observed
        with self.assertRaisesRegex(ValueError, "pair_teardown"):
            p.compare_fixed_case(producer, consumer)

    def test_adapter_declared_budget_and_settings_are_observed(self):
        summary = {"model": "local-openai:" + p.ALIAS, "model_settings": p.SETTINGS,
                   "tool_hint_mode": "none", "max_iterations": 4, "projection": ["read_file", "write_file"]}
        def raw(value):
            return {"candidate_stdout_tail": "OPENWORKER_SUMMARY=" + json.dumps(value) + "\n"}
        self.assertEqual(p.adapter_settings(raw(summary))["max_iterations"], 4)
        for field in summary:
            changed = copy.deepcopy(summary)
            changed[field] = None
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "adapter_configuration"):
                p.adapter_settings(raw(changed))
        duplicated = raw(summary)
        duplicated["candidate_stdout_tail"] *= 2
        with self.assertRaisesRegex(ValueError, "unique_adapter_summary"):
            p.adapter_settings(duplicated)

    def test_receipt_join_requires_acceptance_and_bounded_calls(self):
        candidate = {"harness": {"name": "openworker"}, "model": {"id": p.ALIAS},
                     "toolset": ["read_file", "write_file"]}
        packet = {"source": {"commit": "a" * 40}, "launch_id": "test-launch",
                  "task_package_digest": "sha256:" + "b" * 64}
        experiment = {"id": "test-experiment"}
        receipt = {"task": {"id": "text-repair-v0", "source_commit": "a" * 40,
                            "package_digest": packet["task_package_digest"]},
                   "launch": {"launch_id": packet["launch_id"], "packet_digest": p.canonical_json_digest(packet)},
                   "candidate": dict(candidate, configuration_digest=p.canonical_json_digest(candidate)),
                   "substrate": {"profile_id": "native-inference-public-cpu-r0", "profile_commit": "a" * 40},
                   "experiment": {"digest": p.canonical_json_digest(experiment)},
                   "observation": {"success": True, "candidate_exit_code": 0, "verifier_exit_code": 0,
                                   "timed_out": False, "engine_error_types": [],
                                   "workload": {"configured_max_iterations": 4,
                                   "model_calls_started": 2, "tool_result_observations": {}}}}
        # Schema validity is already the canonical runner's separate contract.
        # These adversarial mutations target this experiment's source/result join.
        with patch.object(p, "schema_check"):
            p.check_receipt(receipt, candidate, packet, experiment, 0)
            mutations = [("candidate_exit_code", 7), ("verifier_exit_code", 1),
                         ("success", False), ("timed_out", True)]
            for key, value in mutations:
                changed = copy.deepcopy(receipt)
                changed["observation"][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    p.check_receipt(changed, candidate, packet, experiment, 0)
            for calls in (0, 5, True, None):
                changed = copy.deepcopy(receipt)
                changed["observation"]["workload"]["model_calls_started"] = calls
                with self.subTest(calls=calls), self.assertRaisesRegex(ValueError, "receipt_call_budget"):
                    p.check_receipt(changed, candidate, packet, experiment, 0)
            changed = copy.deepcopy(receipt)
            changed["observation"]["engine_error_types"] = ["ProviderError"]
            with self.assertRaisesRegex(ValueError, "inference_engine_error"):
                p.check_receipt(changed, candidate, packet, experiment, 0)
            changed["observation"].pop("engine_error_types")
            with self.assertRaisesRegex(ValueError, "inference_engine_error"):
                p.check_receipt(changed, candidate, packet, experiment, 0)
            for field in ("task", "launch", "candidate", "substrate", "experiment"):
                changed = copy.deepcopy(receipt)
                changed[field] = {key: "drift" for key in changed[field]}
                with self.subTest(field=field), self.assertRaises(ValueError):
                    p.check_receipt(changed, candidate, packet, experiment, 0)


if __name__ == "__main__":
    unittest.main()
