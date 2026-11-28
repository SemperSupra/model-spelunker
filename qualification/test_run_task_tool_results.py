"""Source-only receipt retention controls; no model, daemon or native harness install."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest

from jsonschema.validators import validator_for

from qualification.adapters.tool_result_observations import (
    ERROR_TYPES, RESULT_LIMIT, STATUSES, ToolResultObserver,
)
from qualification.run_task import TOOL_RESULT_SUMMARY_MAX_BYTES, tool_action_summary, tool_result_summary


ROOT = Path(__file__).resolve().parents[1]
FIELD = "tool_result_observations"
PREFIX = "OPENWORKER_SUMMARY="
CANARY = "PRIVATE_CANARY_paths_arguments_contents_messages_credentials"
EVIDENCE_DIR = None
RECEIPTS = []


def marker(observation, **extra):
    return PREFIX + json.dumps({"tool_calls": ["read_file"], FIELD: observation, **extra})


def observer_result(status="error", error_type="FileNotFoundError"):
    observer = ToolResultObserver({"list_files", "read_file", "write_file"})
    observer.observe_event("EventType.TOOL_STARTED", {"name": "read_file"})
    observer.audit({"stage": "finished", "tool": "read_file", "status": status,
                    "result": {"error_type": error_type}})
    observer.observe_event("EventType.TOOL_FINISHED", {"name": "read_file", "status": status})
    return observer.snapshot()


def schema_validator(schema):
    cls = validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


def source_commit():
    return os.environ.get("GITHUB_SHA") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


class ToolResultRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads((ROOT / "qualification/run-receipt.schema.json").read_text())
        cls.schema = schema["properties"]["observation"]["properties"]["workload"]["properties"][FIELD]
        cls.validator = schema_validator(cls.schema)

    def project(self, snapshot):
        return tool_result_summary(marker(snapshot), "openworker")

    def test_actual_observer_statuses_and_error_allowlist(self):
        for status in sorted(STATUSES):
            observed = observer_result(status)
            self.assertEqual(self.project(observed), {FIELD: observed})
            self.validator.validate(observed)
        for error in sorted(ERROR_TYPES):
            observed = observer_result(error_type=error)
            self.assertEqual(self.project(observed)[FIELD]["results"][0]["error_type"], error)
        row_schema = self.schema["properties"]["results"]["items"]["properties"]
        self.assertEqual(set(row_schema["error_type"]["enum"]), ERROR_TYPES | {"unknown"})
        self.assertEqual(set(row_schema["status"]["enum"]), STATUSES | {"unknown"})
        self.assertEqual(self.schema["properties"]["limit"]["const"], RESULT_LIMIT)

    def test_explicit_zero_and_unknown_are_distinct_from_absence(self):
        observer = ToolResultObserver({"read_file"})
        zero = observer.snapshot()
        self.assertEqual(self.project(zero), {FIELD: zero})
        observer.observe_event("EventType.TOOL_FINISHED", {"name": CANARY, "status": CANARY})
        unknown = observer.snapshot()
        self.assertEqual(self.project(unknown), {FIELD: unknown})
        self.assertEqual(unknown["results"], [
            {"index": 1, "tool": "unknown", "status": "unknown", "error_type": "unknown"}])
        for raw in ("", PREFIX + "{}", PREFIX + "[]", PREFIX + "null", marker(None)):
            self.assertEqual(tool_result_summary(raw, "openworker"), {})
        for harness in (None, "goose", "OpenWorker", [], {}):
            self.assertEqual(tool_result_summary(marker(zero), harness), {})

    def test_repeated_events_overflow_and_independent_audit_counts(self):
        observer = ToolResultObserver({"read_file"})
        for _ in range(RESULT_LIMIT + 7):
            observer.observe_event("EventType.TOOL_FINISHED", {"name": "read_file", "status": "error"})
        below = observer.snapshot()
        self.assertEqual(below["finished_audit_count"], 0)
        self.assertEqual(self.project(below), {FIELD: below})
        for _ in range(40):
            observer.audit({"stage": "finished", "tool": "read_file", "status": "error"})
        above = observer.snapshot()
        self.assertEqual(self.project(above), {FIELD: above})
        self.assertEqual(above["event_count"], 31)
        self.assertEqual(above["omitted_count"], 7)
        self.assertEqual([r["index"] for r in above["results"]], list(range(1, 25)))
        self.assertEqual(above["finished_audit_count"], 40)

    def test_raw_canaries_and_unknown_fields_are_not_retained(self):
        observation = observer_result()
        expected = copy.deepcopy(observation)
        observation["private"] = {"path": CANARY}
        observation["results"][0].update(arguments=CANARY, result_preview=CANARY, message=CANARY)
        summary = marker(observation, raw_output=CANARY, approvals=[{"path": CANARY}])
        original = copy.deepcopy(observation)
        retained = tool_result_summary(summary, "openworker")
        self.assertEqual(retained, {FIELD: expected})
        self.assertNotIn(CANARY, json.dumps(retained))
        self.assertEqual(observation, original)
        self.validator.validate(retained[FIELD])

    def test_malformed_shapes_counts_and_indices_stay_absent(self):
        valid = observer_result()
        mutations = []
        for key in ("event_count", "finished_audit_count", "omitted_count", "limit"):
            for value in (-1, True, 1.5, "1", None):
                mutations.append((key, {**valid, key: value}))
        mutations.extend([
            ("version", {**valid, "version": "future-or-secret-format"}),
            ("limit", {**valid, "limit": 25}),
            ("empty", {**valid, "results": []}),
            ("wrong-total", {**valid, "event_count": 2}),
            ("wrong-omitted", {**valid, "omitted_count": 1}),
            ("not-list", {**valid, "results": {}}),
            ("not-row", {**valid, "results": [None]}),
            ("too-many", {**valid, "event_count": 25,
                          "results": [{**valid["results"][0], "index": i} for i in range(1, 26)]}),
            ("duplicate-index", {**valid, "event_count": 2, "results": valid["results"] * 2}),
        ])
        for value in (0, 2, True, "1", None):
            mutations.append(("index", {**valid, "results": [{**valid["results"][0], "index": value}]}))
        for key in valid:
            bad = copy.deepcopy(valid)
            del bad[key]
            mutations.append(("missing-" + key, bad))
        for label, bad in mutations:
            with self.subTest(label=label, value=bad):
                self.assertEqual(self.project(bad), {})

    def test_invalid_labels_and_unjustified_error_classes_stay_absent(self):
        valid = observer_result()
        for key in ("tool", "status", "error_type"):
            for value in (CANARY, [], None):
                bad = copy.deepcopy(valid)
                bad["results"][0][key] = value
                self.assertEqual(self.project(bad), {})
                self.assertTrue(list(self.validator.iter_errors(bad)))
        for key, value in (("status", "ok"), ("tool", "unknown")):
            bad = copy.deepcopy(valid)
            bad["results"][0][key] = value
            self.assertEqual(self.project(bad), {})
            self.assertTrue(list(self.validator.iter_errors(bad)))
        self.assertEqual(self.project({**valid, "finished_audit_count": 0}), {})
        two_errors = {**valid, "event_count": 2,
                      "results": valid["results"] + [{**valid["results"][0], "index": 2}]}
        self.assertEqual(self.project(two_errors), {})
        self.assertIn(FIELD, self.project({**two_errors, "finished_audit_count": 2}))

    def test_duplicate_markers_and_duplicate_keys_are_ambiguous(self):
        raw = marker(observer_result())
        for stdout in (raw + "\n" + raw, raw + "\n" + PREFIX + "{}", PREFIX + "{}\n" + raw):
            self.assertEqual(tool_result_summary(stdout, "openworker"), {})
        for old, new in (
            ('"tool_calls": ["read_file"]', '"tool_calls": [], "tool_calls": ["read_file"]'),
            ('"event_count": 1', '"event_count": 1, "event_count": 1'),
            ('"index": 1', '"index": 1, "index": 1'),
        ):
            duplicate = raw.replace(old, new)
            self.assertNotEqual(raw, duplicate)
            self.assertEqual(tool_result_summary(duplicate, "openworker"), {})
        self.assertEqual(tool_result_summary(" " + raw, "openworker"), {})

    def test_byte_limit_and_malformed_json_never_manufacture_evidence(self):
        valid = marker(observer_result())
        padded = valid + " " * (TOOL_RESULT_SUMMARY_MAX_BYTES - len(valid[len(PREFIX):].encode()))
        self.assertIn(FIELD, tool_result_summary(padded, "openworker"))
        self.assertEqual(tool_result_summary(padded + " ", "openworker"), {})
        unicode_raw = PREFIX + json.dumps({FIELD: observer_result(), "ignored": "é" * 33000}, ensure_ascii=False)
        self.assertLess(len(unicode_raw), TOOL_RESULT_SUMMARY_MAX_BYTES)
        self.assertEqual(tool_result_summary(unicode_raw, "openworker"), {})
        deep = valid[:-1] + ', "ignored": ' + "[" * 10000 + "0" + "]" * 10000 + "}"
        huge_int = PREFIX + '{"tool_calls": [], "ignored": ' + "9" * 5000 + "}"
        for raw in (PREFIX + "{invalid}", deep, huge_int, valid + " trailing", valid + "\ud800"):
            self.assertEqual(tool_result_summary(raw, "openworker"), {})
        for constant in ("NaN", "Infinity", "-Infinity"):
            self.assertEqual(tool_result_summary(valid[:-1] + ', "ignored": ' + constant + "}", "openworker"), {})
        self.assertEqual(tool_action_summary(deep), {})
        self.assertEqual(tool_action_summary(huge_int), {})

    def test_closed_schema_rejects_extra_fields_and_invalid_counts(self):
        valid = observer_result()
        for key in ("event_count", "finished_audit_count", "omitted_count"):
            for value in (-1, True, 1.5, "1", None):
                self.assertTrue(list(self.validator.iter_errors({**valid, key: value})))
        self.assertTrue(list(self.validator.iter_errors({**valid, "raw": CANARY})))
        extra_row = copy.deepcopy(valid)
        extra_row["results"][0]["raw"] = CANARY
        self.assertTrue(list(self.validator.iter_errors(extra_row)))
        for key in valid:
            missing = copy.deepcopy(valid)
            del missing[key]
            self.assertTrue(list(self.validator.iter_errors(missing)))


class CanonicalRunnerToolResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = schema_validator(json.loads((ROOT / "qualification/run-receipt.schema.json").read_text()))

    def run_fixture(self, label, stdout, *, ready=True, harness="openworker", retention=True):
        with tempfile.TemporaryDirectory(prefix="tool-result-contract-") as tmp:
            directory = Path(tmp)
            candidate = directory / "candidate.py"
            candidate.write_text(
                "from pathlib import Path\n"
                + f"Path('value.txt').write_bytes({b'READY\n' if ready else b'WRONG\n'!r})\n"
                + f"print({stdout!r})\n", encoding="utf-8")
            metadata = directory / "candidate.json"
            metadata.write_text(json.dumps({
                "harness": {"name": harness, "version": "synthetic-summary-contract-v1"},
                "model": {"provider": "none", "id": "none"},
                "toolset": ["read_file", "write_file"],
            }), encoding="utf-8")
            receipt_path = directory / "receipt.json"
            if retention:
                prefix = [sys.executable, str(ROOT / "qualification/run_task.py")]
            else:
                # Same canonical main/process containment and stdout, with only
                # the new optional projection disabled for a parity control.
                code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
                        "from qualification import run_task; "
                        "run_task.tool_result_summary = lambda *args: {}; "
                        "raise SystemExit(run_task.main())")
                prefix = [sys.executable, "-c", code]
            proc = subprocess.run(prefix + [
                "--task-commit", source_commit(),
                "--substrate-profile-id", "synthetic-tool-result-" + sys.platform,
                "--substrate-profile-commit", source_commit(),
                str(ROOT / "qualification/tasks/text-repair-v0"), str(metadata), str(receipt_path),
                "--", sys.executable, str(candidate),
            ], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(proc.returncode, 0 if ready else 1, proc.stdout + proc.stderr)
            raw = receipt_path.read_bytes()
            receipt = json.loads(raw)
            self.validator.validate(receipt)
            self.assertNotIn(CANARY, raw.decode())
            self.assertNotIn(CANARY, proc.stdout)
            if EVIDENCE_DIR is not None:
                name = label + ".json"
                (EVIDENCE_DIR / name).write_bytes(raw)
                RECEIPTS.append({"file": name, "bytes": len(raw),
                                 "sha256": hashlib.sha256(raw).hexdigest(), "run_id": receipt["run_id"]})
            return receipt

    def test_real_runner_preserves_outcomes_and_evidence_with_retention(self):
        observed = observer_result()
        stdout = marker(observed, max_iterations=4, raw=CANARY)
        for ready in (True, False):
            label = "accepted" if ready else "rejected"
            baseline = self.run_fixture(label + "-control", stdout, ready=ready, retention=False)
            retained = self.run_fixture(label + "-retained", stdout, ready=ready)
            self.assertEqual(retained["observation"]["workload"][FIELD], observed)
            self.assertEqual(retained["observation"]["success"], ready)
            self.assertNotEqual(baseline["run_id"], retained["run_id"])
            self.assertEqual(baseline["evidence_digest"], retained["evidence_digest"])
            for row in (baseline, retained):
                row.pop("run_id")
                row["observation"].pop("wall_seconds")
                row["observation"]["workload"].pop(FIELD, None)
            self.assertEqual(baseline, retained)

    def test_real_runner_omits_unusable_evidence_without_changing_acceptance(self):
        valid = marker(observer_result())
        cases = {
            "absent": PREFIX + '{"tool_calls": ["read_file"]}',
            "ambiguous": valid + "\n" + valid,
            "invalid-count": marker({**observer_result(), "event_count": True}),
            "deep-json": valid[:-1] + ', "ignored": ' + "[" * 10000 + "0" + "]" * 10000 + "}",
            "huge-integer": PREFIX + '{"tool_calls": [], "ignored": ' + "9" * 5000 + "}",
            "oversized": valid + " " * TOOL_RESULT_SUMMARY_MAX_BYTES,
        }
        for label, stdout in cases.items():
            with self.subTest(label=label):
                receipt = self.run_fixture(label, stdout)
                self.assertTrue(receipt["observation"]["success"])
                self.assertNotIn(FIELD, receipt["observation"]["workload"])
        wrong_source = self.run_fixture("other-harness", valid, harness="contract-test")
        self.assertNotIn(FIELD, wrong_source["observation"]["workload"])
        wrong_source["observation"]["workload"][FIELD] = observer_result()
        self.assertTrue(list(self.validator.iter_errors(wrong_source)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    EVIDENCE_DIR = args.evidence_dir
    if EVIDENCE_DIR is not None:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=False)
    result = unittest.main(argv=[sys.argv[0]], verbosity=2, exit=False).result
    if EVIDENCE_DIR is not None:
        paths = [
            "qualification/run_task.py", "qualification/run-receipt.schema.json",
            "qualification/test_run_task_tool_results.py", "qualification/adapters/tool_result_observations.py",
            "qualification/windows_containment.py", "qualification/endpoint_policy.py",
            "qualification/tasks/text-repair-v0/task.json", "qualification/tasks/text-repair-v0/verify.py",
            ".github/workflows/qualification-contract.yml",
        ]
        evidence = {
            "scope": "SYNTHETIC_CANONICAL_RECEIPT_CONTRACT_ONLY", "source_commit": source_commit(),
            "workflow": {key: os.environ.get(key) for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")},
            "platform": {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()},
            "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths},
            "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
            "skips": len(result.skipped), "receipts": RECEIPTS, "model_attempts": 0,
            "limitations": "Scripted stdout and real canonical runner; no native engine or model inference; source/receipt witnesses are not authentication.",
        }
        (EVIDENCE_DIR / "contract-evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("TOOL_RESULT_RETENTION_CONTRACT=" + json.dumps(evidence, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() else 1)
