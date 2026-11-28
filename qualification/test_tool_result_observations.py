"""Privacy, ambiguity, and bounds of the passive native-result projection."""

import copy
import json
import unittest

from qualification.adapters.tool_result_observations import RESULT_LIMIT, ToolResultObserver


FINISHED = "EventType.TOOL_FINISHED"


class ToolResultObservationTests(unittest.TestCase):
    def setUp(self):
        self.observer = ToolResultObserver({"read_file", "write_file"})

    @staticmethod
    def audit(**overrides):
        return {"stage": "finished", "tool": "read_file", "status": "error",
                "result": {"error_type": "FileNotFoundError"}, **overrides}

    def test_success_exception_denial_and_interruption_remain_distinct(self):
        for status in ("ok", "error", "denied", "interrupted"):
            self.observer.observe_event("EventType.TOOL_STARTED", {"name": "read_file"})
            self.observer.audit(self.audit(status=status))
            self.observer.observe_event(FINISHED, {"name": "read_file", "status": status})
        rows = self.observer.snapshot()["results"]
        self.assertEqual([r["status"] for r in rows], ["ok", "error", "denied", "interrupted"])
        self.assertEqual([r["error_type"] for r in rows],
                         ["unknown", "FileNotFoundError", "unknown", "unknown"])

    def test_unknown_and_missing_values_are_never_inferred_from_text(self):
        for payload in ({}, {"name": [], "status": {}},
                        {"name": "unprojected", "status": "success"}):
            self.observer.observe_event(FINISHED, payload)
        self.observer.audit(self.audit(result={"error": "FileNotFoundError: missing"}))
        self.observer.observe_event(FINISHED, {"name": "read_file", "status": "error"})
        rows = self.observer.snapshot()["results"]
        self.assertEqual([r["tool"] for r in rows[:3]], ["unknown"] * 3)
        self.assertEqual([r["status"] for r in rows[:3]], ["unknown"] * 3)
        self.assertEqual([r["error_type"] for r in rows], ["unknown"] * 4)
        for payload in (None, [], "not a native payload"):
            self.observer.audit(payload)
            self.observer.observe_event(FINISHED, payload)
        self.assertEqual([r["status"] for r in self.observer.snapshot()["results"][4:]],
                         ["unknown"] * 3)

    def test_missing_duplicate_mismatched_and_intervening_audits_do_not_join(self):
        cases = {
            "missing": [],
            "duplicate": [self.audit(), self.audit()],
            "wrong-tool": [self.audit(tool="write_file")],
            "wrong-status": [self.audit(status="ok")],
            "intervening-audit": [self.audit(), {"stage": "started"}],
            "intervening-event": [self.audit(), "EventType.MODEL_TURN"],
            "unknown-class": [self.audit(result={"error_type": "ApplicationSecretError"})],
        }
        for label, inputs in cases.items():
            with self.subTest(label=label):
                observer = ToolResultObserver({"read_file", "write_file"})
                observer.observe_event("EventType.TOOL_STARTED", {"name": "read_file"})
                for item in inputs:
                    if isinstance(item, str):
                        observer.observe_event(item, {})
                    else:
                        observer.audit(item)
                observer.observe_event(FINISHED, {"name": "read_file", "status": "error"})
                self.assertEqual(observer.snapshot()["results"][0]["error_type"], "unknown")
                # A matching audit received after its event is not used retroactively.
                observer.audit(self.audit())
                self.assertEqual(observer.snapshot()["results"][0]["error_type"], "unknown")
                observer.observe_event(FINISHED, {"name": "read_file", "status": "error"})
                self.assertEqual(observer.snapshot()["results"][1]["error_type"], "unknown")

    def test_repeated_events_are_observations_not_deduplicated_calls(self):
        self.observer.observe_event("EventType.TOOL_STARTED", {"name": "read_file"})
        self.observer.audit(self.audit())
        for _ in range(2):
            self.observer.observe_event(FINISHED, {"name": "read_file", "status": "error"})
        snapshot = self.observer.snapshot()
        self.assertEqual(snapshot["event_count"], 2)
        self.assertEqual(snapshot["finished_audit_count"], 1)
        self.assertEqual([r["index"] for r in snapshot["results"]], [1, 2])
        self.assertEqual([r["error_type"] for r in snapshot["results"]],
                         ["FileNotFoundError", "unknown"])

    def test_retained_records_are_bounded_with_explicit_overflow(self):
        for _ in range(RESULT_LIMIT + 7):
            self.observer.audit(self.audit())
            self.observer.observe_event(FINISHED, {"name": "read_file", "status": "error"})
        snapshot = self.observer.snapshot()
        self.assertEqual(len(snapshot["results"]), RESULT_LIMIT)
        self.assertEqual(snapshot["event_count"], RESULT_LIMIT + 7)
        self.assertEqual(snapshot["finished_audit_count"], RESULT_LIMIT + 7)
        self.assertEqual(snapshot["omitted_count"], 7)

    def test_canary_privacy_and_input_immutability(self):
        canary = "PRIVATE_CANARY_arguments_paths_messages_content_secrets"
        audit = self.audit(arguments={"path": canary, "content": canary},
                           result={"error_type": canary, "error": canary},
                           result_preview=canary, reason=canary, unknown_field=canary)
        event = {"name": "read_file", "status": "error", "result_preview": canary,
                 "error_type": "FileNotFoundError", "reason": canary, "path": canary}
        original = copy.deepcopy((audit, event))
        self.observer.observe_event("EventType.TOOL_STARTED", {"name": "read_file"})
        self.observer.audit(audit)
        self.observer.observe_event(FINISHED, event)
        self.observer.observe_event(FINISHED, {"name": canary, "status": canary})
        snapshot = self.observer.snapshot()
        self.assertNotIn(canary, json.dumps(snapshot))
        self.assertEqual(snapshot["results"][0]["error_type"], "unknown")
        self.assertEqual((audit, event), original)
        snapshot["results"][0]["status"] = canary
        self.assertNotIn(canary, json.dumps(self.observer.snapshot()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
