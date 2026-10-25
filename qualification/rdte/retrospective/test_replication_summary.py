from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qualification.rdte.retrospective.summarize_replications import summarize


def write_rep(root: Path, family: str, wall: float, rss: int) -> None:
    root.mkdir(parents=True)
    if family == "goose":
        trace = {
            "summary": {
                "event_count": 3,
                "assistant_message_groups": 2,
                "tool_request_count": 1,
                "tool_response_count": 1,
                "tool_error_count": 0,
            },
            "events": [
                {
                    "type": "message",
                    "message_id": "a1",
                    "role": "assistant",
                    "content": [{"kind": "tool_request", "tool_name": "edit"}],
                },
                {
                    "type": "message",
                    "message_id": "u1",
                    "role": "user",
                    "content": [{"kind": "tool_response", "response_status": "success"}],
                },
            ],
        }
    else:
        trace = {
            "summary": {
                "event_count": 4,
                "model_call_started_count": 2,
                "provider_observation_count": 2,
            },
            "events": [
                {"type": "EventType.TURN_START", "tool_names": []},
                {"type": "EventType.TOOL_PROPOSED", "tool_names": ["write_file"]},
                {"type": "EventType.TOOL_FINISHED", "tool_names": []},
                {"type": "EventType.TURN_END", "tool_names": []},
            ],
        }
    run = {
        "execution": {
            "candidate_exit_code": 0,
            "state_changed": True,
            "verifier_pass": True,
        },
        "resources": {"wall_seconds": wall, "max_rss_kbytes": rss},
        "trace_summary": trace["summary"],
    }
    (root / "trace.json").write_text(json.dumps(trace))
    (root / "run-summary.json").write_text(json.dumps(run))


class ReplicationSummaryTests(unittest.TestCase):
    def test_counts_stable_variants_within_each_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            goose = [root / "g1", root / "g2"]
            ow = [root / "o1", root / "o2"]
            write_rep(goose[0], "goose", 10.0, 100)
            write_rep(goose[1], "goose", 12.0, 110)
            write_rep(ow[0], "openworker", 5.0, 80)
            write_rep(ow[1], "openworker", 7.0, 82)

            result = summarize(goose_roots=goose, openworker_roots=ow)
            self.assertEqual(len(result["cohorts"]), 2)
            for cohort in result["cohorts"]:
                self.assertEqual(cohort["rep_count"], 2)
                self.assertEqual(cohort["native_process_variant_count"], 1)
                self.assertEqual(cohort["coarse_anchor_variant_count"], 1)
                self.assertEqual(cohort["outcome_variant_count"], 1)
            self.assertFalse(
                result["interpretation"]["cross_harness_ranking_performed"]
            )
            self.assertFalse(result["interpretation"]["conformance_model_built"])


if __name__ == "__main__":
    unittest.main()
