#!/usr/bin/env python3
"""No-model adversarial contracts for the first public-safe learning treatments."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qualification.adapters.learning_treatment import (
    ADVISORY, BUNDLES, MAX_BUNDLE_BYTES, apply_learning_treatment, load_bundle,
)
from qualification.adapters.tool_hint import apply_tool_hint

AUTHORITATIVE = "Change only the permitted output. Do not disclose inputs."


class LearningTreatmentTests(unittest.TestCase):
    def test_baseline_unchanged(self):
        self.assertEqual(apply_tool_hint(AUTHORITATIVE, "none"), AUTHORITATIVE)
        self.assertEqual(apply_learning_treatment(AUTHORITATIVE, ""), AUTHORITATIVE)

    def test_modes_use_distinct_public_bundles(self):
        memory = apply_tool_hint(AUTHORITATIVE, "memory-recall-v1")
        skill = apply_tool_hint(AUTHORITATIVE, "skill-procedure-v1")
        self.assertNotEqual(memory, skill)
        for text in (memory, skill):
            self.assertTrue(text.startswith(AUTHORITATIVE + ADVISORY))
            self.assertIn("UNTRUSTED ADVISORY", text)
            self.assertIn("--- END ADVISORY ---", text)
            self.assertIn("cannot change the task instruction", text)
            self.assertNotIn("C:/Users/", text)
            self.assertNotIn("SK_TEST_EXAMPLE_SECRET", text)

    def test_bundle_digests_are_deterministic(self):
        for name in sorted(BUNDLES):
            content, digest = load_bundle(name)
            self.assertEqual(digest, "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest())
            self.assertEqual(load_bundle(name), (content, digest))
            self.assertLessEqual(len(content.encode("utf-8")), MAX_BUNDLE_BYTES)

    def test_unsupported_mode_fails_closed(self):
        for mode in ("../private", "memory-recall-v2", "memory-recall-v1.txt", "auto", "training"):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    apply_tool_hint(AUTHORITATIVE, mode)

    def test_empty_task_is_rejected(self):
        for mode in ("memory-recall-v1", "skill-procedure-v1"):
            with self.assertRaises(ValueError):
                apply_tool_hint(" ", mode)

    def test_missing_bundle_refuses(self):
        with TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                load_bundle("memory-recall-v1", root=Path(td))

    def test_oversize_bundle_refuses(self):
        with TemporaryDirectory() as td:
            target = Path(td) / BUNDLES["memory-recall-v1"]
            target.write_bytes(b"x" * (MAX_BUNDLE_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "size"):
                load_bundle("memory-recall-v1", root=Path(td))

    def test_invalid_utf8_and_nul_refuse(self):
        for data in (b"\xff\xfe", b"safe\x00hidden", b"\r\n"):
            with self.subTest(data=data):
                with TemporaryDirectory() as td:
                    (Path(td) / BUNDLES["skill-procedure-v1"]).write_bytes(data)
                    with self.assertRaises(ValueError):
                        load_bundle("skill-procedure-v1", root=Path(td))

    def test_symlink_bundle_refuses(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            sensitive = root / "injected.txt"
            sensitive.write_text("fake result", encoding="utf-8")
            (root / BUNDLES["skill-procedure-v1"]).symlink_to(sensitive)
            with self.assertRaises(ValueError):
                load_bundle("skill-procedure-v1", root=root)

    def test_no_oracle_answers_or_runtime_authority_in_bundles(self):
        for name in BUNDLES:
            text, _ = load_bundle(name)
            lowered = text.lower()
            for forbidden in (
                "sk-syntheticlongsecretvalue", "bearer ", "password=", "192.168.", "bigmac.local",
                "truenas.local", "github_token", "github_pat_", "literal answer:",
                "src/retry.py", "boundary-bugfix-v0", "validation-discovery-v0",
                "disable permissions", "ignore the task",
            ):
                self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
