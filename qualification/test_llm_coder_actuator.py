#!/usr/bin/env python3
"""Red/Blue security and policy tests for qualification/adapters/llm_coder_actuator.py."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "llm_coder_actuator", ROOT / "qualification" / "adapters" / "llm_coder_actuator.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class ActuatorConfinementAndPolicyTests(unittest.TestCase):
    def test_rejects_absolute_write_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            with self.assertRaisesRegex(MOD.ActuatorPolicyError, "absolute path prohibited"):
                MOD.resolve_confined_target("/etc/passwd", workspace_root=ws)

    def test_rejects_parent_directory_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            with self.assertRaisesRegex(MOD.ActuatorPolicyError, "parent traversal prohibited"):
                MOD.resolve_confined_target("../escape.py", workspace_root=ws)
            with self.assertRaisesRegex(MOD.ActuatorPolicyError, "parent traversal prohibited"):
                MOD.resolve_confined_target("src/../../escape.py", workspace_root=ws)

    def test_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp_ws, tempfile.TemporaryDirectory() as tmp_out:
            ws = Path(tmp_ws)
            outside = Path(tmp_out) / "secret.py"
            outside.write_text("secret = 1\n", encoding="utf-8")
            link = ws / "evil.py"
            link.symlink_to(outside)
            with self.assertRaisesRegex(MOD.ActuatorPolicyError, "symlink component prohibited"):
                MOD.resolve_confined_target("evil.py", workspace_root=ws)

    def test_enforces_allowed_write_paths_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "src").mkdir()
            (ws / "src" / "retry.py").write_text("x = 1\n", encoding="utf-8")
            resolved = MOD.resolve_confined_target(
                "src/retry.py",
                workspace_root=ws,
                allowed_write_paths=["src/retry.py"],
            )
            self.assertEqual(resolved, (ws / "src" / "retry.py").resolve())
            with self.assertRaisesRegex(MOD.ActuatorPolicyError, "not in allowed_write_paths"):
                MOD.resolve_confined_target(
                    "src/other.py",
                    workspace_root=ws,
                    allowed_write_paths=["src/retry.py"],
                )

    def test_blocks_paid_deepseek_and_sambanova_routes_locally(self):
        for forbidden in (
            "deepseek/deepseek-chat",
            "deepseek/deepseek-v4.1-flash",
            "openrouter/deepseek/deepseek-r1",
            "sambanova/meta-llama-405b",
        ):
            with self.subTest(model=forbidden):
                with self.assertRaisesRegex(MOD.ActuatorPolicyError, "PAID_PROVIDER_BLOCKED"):
                    MOD.check_route_policy(forbidden)

        with mock.patch.dict(os.environ, {"MODEL_SPELUNKER_PROVIDER_PIN": "deepseek"}):
            with self.assertRaisesRegex(MOD.ActuatorPolicyError, "PAID_PROVIDER_BLOCKED"):
                MOD.check_route_policy("openai/gpt-oss-20b")

    def test_blocks_unapproved_paid_cloud_routes_by_default(self):
        with self.assertRaisesRegex(MOD.ActuatorPolicyError, "UNAPPROVED_CLOUD_ROUTE_BLOCKED"):
            MOD.check_route_policy("anthropic/claude-4-opus")

    def test_allows_explicit_free_and_audited_byok_routes(self):
        raw, order = MOD.check_route_policy("nvidia/nemotron-3-ultra-550b-a55b:free")
        self.assertEqual(raw, "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.assertEqual(order, ["nvidia"])

        raw2, order2 = MOD.check_route_policy("google/gemini-3.7-flash")
        self.assertEqual(raw2, "google/gemini-3.7-flash")
        self.assertEqual(order2, ["google-ai-studio"])

    def test_sanitizes_bearer_and_openrouter_secrets(self):
        raw_err = "Auth failed for Bearer sk-or-v1-abcdef1234567890 and key TopSecretKey999"
        redacted = MOD.sanitize_text(raw_err, "TopSecretKey999")
        self.assertNotIn("sk-or-v1-abcdef1234567890", redacted)
        self.assertNotIn("TopSecretKey999", redacted)
        self.assertIn("[REDACTED_SECRET]", redacted)


if __name__ == "__main__":
    unittest.main()
