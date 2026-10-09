import json
from pathlib import Path
import tempfile
import unittest

from qualification.validate_portable_launch_packet import (
    canonical_digest,
    validate_harness_realization_binding,
)


class HarnessRealizationBindingTests(unittest.TestCase):
    def create_profile(self, root: Path):
        rel="qualification/harness-realizations/example.json"
        path=root/rel
        path.parent.mkdir(parents=True,exist_ok=True)
        profile={
            "schema_version":1,
            "record_type":"harness-realization-profile",
            "id":"goose-test-control",
            "harness":{"name":"goose","source_revision":"2090ad1c65ddb39497601a936a9fe17d66254bfe"},
        }
        path.write_text(json.dumps(profile),encoding="utf-8")
        actor={
            "harness":{
                "name":"goose",
                "version":"1.51.0",
                "realization":{
                    "profile_ref":rel,
                    "profile_digest":canonical_digest(profile),
                },
            }
        }
        return path, actor

    def test_legacy_actor_without_binding_stays_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            validate_harness_realization_binding(
                {"harness":{"name":"goose","version":"1.51.0"}},Path(td)
            )

    def test_exact_realization_binding_passes(self):
        with tempfile.TemporaryDirectory() as td:
            _, actor=self.create_profile(Path(td))
            validate_harness_realization_binding(actor,Path(td))

    def test_profile_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path,actor=self.create_profile(Path(td))
            profile=json.loads(path.read_text())
            profile["build"]={"compiler_flags":["-C target-cpu=native"]}
            path.write_text(json.dumps(profile),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"digest mismatch"):
                validate_harness_realization_binding(actor,Path(td))

    def test_cross_harness_reuse_fails(self):
        with tempfile.TemporaryDirectory() as td:
            _, actor=self.create_profile(Path(td))
            actor["harness"]["name"]="openworker"
            with self.assertRaisesRegex(ValueError,"name mismatch"):
                validate_harness_realization_binding(actor,Path(td))

    def test_path_escape_fails(self):
        with tempfile.TemporaryDirectory() as td:
            _, actor=self.create_profile(Path(td))
            actor["harness"]["realization"]["profile_ref"]="qualification/harness-realizations/../../../secret.json"
            with self.assertRaisesRegex(ValueError,"escapes repository"):
                validate_harness_realization_binding(actor,Path(td))

    def test_hash_changes_actor_candidate_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path,actor=self.create_profile(Path(td))
            before=canonical_digest(actor)
            profile=json.loads(path.read_text())
            profile["experiment"]={"role":"candidate"}
            path.write_text(json.dumps(profile),encoding="utf-8")
            actor["harness"]["realization"]["profile_digest"]=canonical_digest(profile)
            after=canonical_digest(actor)
            self.assertNotEqual(before,after)
            validate_harness_realization_binding(actor,Path(td))


if __name__=="__main__":
    unittest.main()
