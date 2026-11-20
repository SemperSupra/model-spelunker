#!/usr/bin/env python3
"""Synthetic security/custody tests for read-only DLE memory bootstrapping."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qualification.dle_context_client import project_context, MAX_CONTEXT_BYTES

DIGEST = "a" * 64
AUTHORITY = "https://github.com/example/public-synthetic/issues/42"
REVISION = "issue-body-sha256:synthetic-rev-04"


def sample():
    return {
        "schema": "dle-context-v1",
        "authority": AUTHORITY,
        "revision": REVISION,
        "sha256": DIGEST,
        "mission": "Implement a bounded synthetic repair",
        "next_action": "Read current issue and run the named verifier",
        "constraints": ["No public release", "Only synthetic fixtures"],
        "unknowns": ["Guest isolation unverified"],
        "github_verified": False,
        "accepted": [
            {"id": "a2", "text": "Prior tool output is not a permit", "source": AUTHORITY, "status": "accepted"},
            {"id": "a1", "text": "Preserve task scope", "source": AUTHORITY, "status": "accepted"},
        ],
    }


class DleBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "context.json"

    def emit(self, document=None):
        self.path.write_text(json.dumps(sample() if document is None else document), encoding="utf-8")

    def project(self, *, revision=REVISION, digest=DIGEST, authority=AUTHORITY):
        return project_context(self.path, expected_authority=authority,
                               expected_revision=revision, expected_sha256=digest)

    def test_source_bound_advisory_minimal_output(self):
        self.emit()
        result = self.project()
        self.assertEqual(result["schema"], "dle-bootstrap-advisory-v1")
        self.assertFalse(result["github_verified"])
        self.assertTrue(result["advisory_only"])
        self.assertEqual(result["revision"], REVISION)
        self.assertEqual([c["id"] for c in result["accepted"]], ["a1", "a2"])
        self.assertNotIn("promotion_authorized", result)
        self.assertNotIn("data_release_authorized", result)
        self.assertEqual(len(result["projection_file_sha256"]), 64)

    def test_wrong_source_revision_and_digest_refuse(self):
        self.emit()
        for override in (
            {"revision": "old"},
            {"authority": "https://github.com/other/public/issues/3"},
            {"digest": "b" * 64},
        ):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, "stale|wrong"):
                    self.project(**override)

    def test_no_self_verified_context(self):
        body = sample()
        for value in (True, None, "true"):
            with self.subTest(value=value):
                body["github_verified"] = value
                self.emit(body)
                with self.assertRaisesRegex(ValueError, "verification"):
                    self.project()

    def test_candidate_cannot_enter_accepted_projection(self):
        body = sample()
        body["accepted"][0]["status"] = "candidate"
        self.emit(body)
        with self.assertRaisesRegex(ValueError, "unaccepted"):
            self.project()

    def test_duplicate_accepted_claim_ids_refuse(self):
        body = sample()
        body["accepted"][0]["id"] = "a1"
        self.emit(body)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.project()

    def test_oversized_and_symlink_context_refuse(self):
        self.path.write_bytes(b"x" * (MAX_CONTEXT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "large"):
            self.project()
        self.path.unlink()
        other = Path(self.tmp.name) / "other.json"
        other.write_text(json.dumps(sample()), encoding="utf-8")
        self.path.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.project()

    def test_malformed_or_poisoned_context_refuses(self):
        body = sample()
        for candidate in (
            {**body, "schema": "unknown-v999"},
            {**body, "mission": 42},
            {**body, "next_action": ""},
            {**body, "constraints": "not a list"},
            {**body, "unknowns": ["bad\x00content"]},
            {**body, "accepted": [{"id": "bad", "text": "claim", "source": AUTHORITY, "status": "accepted"}, {"id": "bad", "text": "claim", "source": AUTHORITY, "status": "accepted"}]},
        ):
            with self.subTest(candidate=candidate):
                self.emit(candidate)
                with self.assertRaises(ValueError):
                    self.project()

    def test_no_arbitrary_source_authentication_via_digest(self):
        body = sample()
        body["mission"] = "Untrusted content can change the mission"
        self.emit(body)
        result = self.project()
        self.assertFalse(result["github_verified"])
        self.assertTrue(result["advisory_only"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
