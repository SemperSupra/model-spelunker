"""Hermetic authorization boundaries for the pinned MAF hydration sidecar."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parent))
from gate import Hold, load_catalog, main, selection

ID="conditioning/toy-encoder"
DIGEST="sha256:"+"a"*64

def approved():
    return {"schema_version":1, "artifacts":{ID:{
        "oci_repository":"ghcr.io/sempersupra/toy-model-artifact",
        "approved_digest":DIGEST,
        "candidate_evidence":{"repository":"SemperSupra/model-artifact-foundry",
                              "commit_sha":"b"*40,"manifest_path":"candidates/toy.json"},
        "upstream_exact_revision":"c"*40,
        "license_spdx_id":"Apache-2.0","approved_at":"2026-11-12T08:00:00Z",
    }}}

class GateTests(unittest.TestCase):
    def test_approved_exact_digest_is_selection_not_hydration(self):
        r=selection(approved(),ID,DIGEST)
        self.assertEqual(r["state"],"APPROVED_CATALOG_ENTRY_RESOLVED_ONLY")
        self.assertFalse(r["hydration_executed"])
        self.assertFalse(r["file_bytes_verified"])
        self.assertEqual(r["oci_reference"],"ghcr.io/sempersupra/toy-model-artifact@"+DIGEST)
    def test_missing_approval(self):
        with self.assertRaisesRegex(Hold,"MODEL_NOT_APPROVED"):
            selection(approved(),"conditioning/unknown",DIGEST)
    def test_mutable_tag_denied(self):
        with self.assertRaisesRegex(Hold,"EXACT_APPROVED_DIGEST"):
            selection(approved(),ID,"latest")
    def test_different_digest_denied(self):
        with self.assertRaisesRegex(Hold,"MODEL_DIGEST_OR_APPROVAL"):
            selection(approved(),ID,"sha256:"+"f"*64)
    def test_foreign_registry_denied(self):
        x=approved()
        x["artifacts"][ID]["oci_repository"]="evil.test/models"
        with self.assertRaisesRegex(Hold,"OCI_REPOSITORY_POLICY_DENIED"):
            selection(x,ID,DIGEST)
    def test_injected_entry_fields_denied(self):
        x=approved()
        x["artifacts"][ID]["arbitrary_shell"]="whoami"
        with self.assertRaisesRegex(Hold,"APPROVED_ENTRY_SCHEMA"):
            selection(x,ID,DIGEST)
    def test_missing_provenance_denied(self):
        x=approved()
        x["artifacts"][ID]["candidate_evidence"]["commit_sha"]="main"
        with self.assertRaisesRegex(Hold,"CANDIDATE_PROVENANCE_UNPINNED"):
            selection(x,ID,DIGEST)
    def test_duplicate_and_nan_field_denied(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"approved.json"
            for text in ('{"schema_version":1,"schema_version":1,"artifacts":{}}',
                         '{"schema_version":NaN,"artifacts":{}}'):
                p.write_text(text)
                with self.assertRaises(Hold):load_catalog(p)
    def test_symlink_and_oversized_catalog_denied(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"approved.json";p.write_text(json.dumps(approved()))
            link=Path(td)/"link.json";link.symlink_to(p)
            with self.assertRaisesRegex(Hold,"CATALOG_UNTRUSTED"):
                load_catalog(link)
            p.write_bytes(b" "* (1024*1024+1))
            with self.assertRaisesRegex(Hold,"CATALOG_TOO_LARGE"):
                load_catalog(p)
    def test_cli_does_not_fetch_in_plan_mode(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"approved.json";p.write_text(json.dumps(approved()))
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                rc=main(["--catalog",str(p),"--id",ID,"--approved-digest",DIGEST])
            self.assertEqual(rc,0)
            result=json.loads(out.getvalue())
            self.assertFalse(result["hydration_executed"])
            self.assertFalse(result["file_bytes_verified"])
    def test_unmounted_hydration_denied(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"approved.json";p.write_text(json.dumps(approved()))
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                rc=main(["--catalog",str(p),"--id",ID,"--approved-digest",DIGEST,
                         "--cache-root",str(Path(td)/"nonexistent"),"--hydrate"])
            self.assertEqual(rc,2)
            self.assertEqual(json.loads(out.getvalue())["status"],"HOLD")

if __name__=="__main__":
    unittest.main()
