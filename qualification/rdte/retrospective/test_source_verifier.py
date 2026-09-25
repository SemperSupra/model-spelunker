from __future__ import annotations

import unittest

from qualification.rdte.retrospective.verify_github_sources import verify_manifest


class SourceVerifierTests(unittest.TestCase):
    def test_commit_tree_and_timestamp_match(self):
        manifest = {
            "rep_id": "x",
            "events": [{
                "type": "MUTATE",
                "at": "2026-09-08T11:55:47Z",
                "source_ref": "https://github.com/o/r/commit/abcdef1",
                "material_id": "git-tree:tree1",
            }],
        }

        def fetch(_url):
            return {
                "commit": {
                    "author": {"date": "2026-09-08T11:55:47Z"},
                    "tree": {"sha": "tree1"},
                }
            }

        report = verify_manifest(manifest, fetch_json=fetch)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["verified_event_count"], 1)

    def test_timestamp_mismatch_fails_closed(self):
        manifest = {
            "rep_id": "x",
            "events": [{
                "type": "PROVIDER_ADMIT",
                "at": "2026-09-08T11:52:33Z",
                "source_ref": "https://github.com/o/r/issues/1",
            }],
        }

        def fetch(_url):
            return {"created_at": "2026-09-08T11:51:47Z"}

        report = verify_manifest(manifest, fetch_json=fetch)
        self.assertEqual(report["status"], "FAIL_SOURCE_MISMATCH")
        self.assertEqual(report["checks"][0]["mismatches"], ["timestamp"])

    def test_unknown_source_is_skipped_not_interpreted(self):
        manifest = {
            "rep_id": "x",
            "events": [{
                "type": "UNKNOWN_GAP",
                "at": None,
                "source_ref": "github-actions:o/r/run/1/job/2",
            }],
        }
        report = verify_manifest(manifest, fetch_json=lambda _url: {})
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            report["checks"][0]["status"],
            "SKIP_UNSUPPORTED_SOURCE",
        )
        self.assertFalse(report["source_interpretation_performed"])


if __name__ == "__main__":
    unittest.main()
