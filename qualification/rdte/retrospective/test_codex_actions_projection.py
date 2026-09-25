from __future__ import annotations

import unittest

from qualification.rdte.retrospective.project_codex_actions_log import project_log


class CodexActionsProjectionTests(unittest.TestCase):
    def test_projects_process_without_retaining_payload(self):
        log = "\n".join([
            'CODEX_STDERR_SIGNALS=[{"line":"INFO SessionConfiguredEvent { session_id: SessionId { uuid: 00000000-0000-0000-0000-000000000001 }, model: \\"qwen\\", model_provider_id: \\"ollama\\" }","t_rel_s":2.0},{"line":"DEBUG codex.turn.reasoning_effort=none Output item item_type=\\"function_call\\"","t_rel_s":29.0},{"line":"INFO ToolCall: write_stdin {\\"secret\\":\\"do-not-retain\\"}","t_rel_s":29.1},{"line":"ERROR failed to parse function arguments: invalid","t_rel_s":29.2},{"line":"INFO tool call completed event.name=\\"codex.tool_call\\"","t_rel_s":29.3},{"line":"DEBUG Output item item_type=\\"message\\"","t_rel_s":30.0}]',
            'OLLAMA_REQUEST_SUMMARY={"body_bytes":100,"body_sha256":"secret-hash","input_bytes":50,"input_items":3,"instructions_chars":20,"model":"qwen","tool_count":5,"reasoning":{"effort":"none"}}',
            'OLLAMA_REQUEST_SUMMARY={"body_bytes":110,"body_sha256":"secret-hash-2","input_bytes":60,"input_items":5,"instructions_chars":20,"model":"qwen","tool_count":5,"reasoning":{"effort":"none"}}',
            'DIAG_CANDIDATE_RC=0',
            'DIAG_VERIFIER_RC=1',
        ])
        result = project_log(log, source_ref="job:1")
        summary = result["summary"]
        self.assertEqual(summary["provider_request_count"], 2)
        self.assertEqual(summary["tool_call_count"], 1)
        self.assertEqual(summary["tool_argument_error_count"], 1)
        self.assertEqual(summary["candidate_exit_code"], 0)
        self.assertEqual(summary["verifier_exit_code"], 1)
        self.assertTrue(summary["completion_validation_mismatch"])
        rendered = str(result)
        self.assertNotIn("do-not-retain", rendered)
        self.assertNotIn("secret-hash", rendered)


if __name__ == "__main__":
    unittest.main()
