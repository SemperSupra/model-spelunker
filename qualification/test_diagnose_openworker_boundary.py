"""Hermetic regression for bounded synthetic after-task diagnostic."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from qualification.diagnose_openworker_boundary import bounded_summary


class BoundaryDiagnosticsTests(unittest.TestCase):
    def fixture(self, root, good=True):
        snapshot=root/"snapshot"
        target=snapshot/"src/retry.py"
        target.parent.mkdir(parents=True)
        if good:
            text="""def backoff_seconds(attempt: int, base: int = 2, cap: int = 30) -> int:
    if attempt <= 0:
        raise ValueError("attempt")
    return min(cap, base ** (attempt - 1))
"""
        else:
            text="""def backoff_seconds(attempt: int, base: int = 2, cap: int = 30) -> int:
    return min(cap, base ** attempt)
"""
        payload=text.encode()
        target.write_bytes(payload)
        (snapshot/"snapshot_manifest.json").write_text(json.dumps({
            "schema_version":1,
            "files":{"src/retry.py":{
                "present":True,
                "size_bytes":len(payload),
                "sha256":"sha256:"+hashlib.sha256(payload).hexdigest(),
            }}
        }))
        receipt=root/"receipt.json"
        receipt.write_text(json.dumps({"task":{"id":"boundary-bugfix-v0"},
                                       "observation":{"success":False},
                                       "evidence_digest":"sha256:"+"a"*64}))
        diagnostics=root/"diag.json"
        diagnostics.write_text(json.dumps({"candidate_stdout_tail":
            'OPENWORKER_SUMMARY='+json.dumps({
                "tool_calls":["list_files","read_file","write_file"],
                "approvals":[{"allowed":True,"path":"src/retry.py"}],
            })+"\n"}))
        return snapshot,diagnostics,receipt

    def test_pass_fail_cases_and_approval_classification(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            snap,diag,receipt=self.fixture(root,good=True)
            found=bounded_summary(snap,diag,receipt)
            self.assertTrue(all(found["case_pass"].values()))
            self.assertTrue(found["python_syntax_valid"])
            self.assertEqual(found["approval_counts"]["allowed"],1)
            self.assertEqual(found["tool_name_counts"]["write_file"],1)
            self.assertNotIn(str(root),str(found))
            self.assertNotIn("backoff_seconds(",str(found))
            self.assertFalse(found["postwrite_accepted"])

    def test_bad_patch_remains_diagnosed_not_promoted(self):
        with tempfile.TemporaryDirectory() as td:
            snap,diag,receipt=self.fixture(Path(td),good=False)
            found=bounded_summary(snap,diag,receipt)
            self.assertFalse(found["case_pass"]["step-1"])
            self.assertFalse(found["case_pass"]["invalid-zero"])
            self.assertFalse(found["postwrite_accepted"])

    def test_modified_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            snap,diag,receipt=self.fixture(Path(td))
            (snap/"src/retry.py").write_text("tampered")
            with self.assertRaisesRegex(ValueError,"snapshot content/hash disagreement"):
                bounded_summary(snap,diag,receipt)

    def test_unknown_tool_name_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            snap,diag,receipt=self.fixture(Path(td))
            data=json.loads(diag.read_text())
            data["candidate_stdout_tail"]='OPENWORKER_SUMMARY='+json.dumps({"tool_calls":["shell"],"approvals":[]})
            diag.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,"not on synthetic workcell allowlist"):
                bounded_summary(snap,diag,receipt)


if __name__ == "__main__":
    unittest.main()
