"""Independent mutation controls for the thin native artifact reuse proof."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from qualification.serving_fanout_r0.native_build_reuse_r0 import proof


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = self.root / "payload"
        (self.payload / "bin").mkdir(parents=True)
        (self.payload / "bin/llama-server").write_bytes(b"synthetic server bytes\n")
        (self.payload / "bin/llama-server").chmod(0o755)
        (self.payload / "bin/libfixture.so").write_bytes(b"synthetic dependency bytes\n")
        self.identity = {"repository": "SemperSupra/model-spelunker", "source_commit": "a" * 40,
                         "run_id": "123", "run_attempt": "1"}
        self.host = {"system": "Linux", "machine": "x86_64", "os_id": "ubuntu", "os_version": "24.04",
                     "libc": ["glibc", "2.39"], "image_os": "ubuntu24", "image_version": "synthetic"}
        tool = {"sha256": "sha256:" + "b" * 64, "version": "synthetic compiler fixture"}
        self.manifest = {
            "schema": proof.SCHEMA, "scope": "SAME_SUBSTRATE_CLI_ONLY", "producer": self.identity,
            "upstream": {"url": proof.UPSTREAM, "revision": proof.REV}, "platform": self.host,
            "build": {"flags": proof.FLAGS, "effective": proof.EFFECTIVE, "parallel_jobs": 2,
                      "toolchain": {name: tool for name in ("c_compiler", "cxx_compiler", "cmake", "linker")},
                      "cmake_cache_sha256": "sha256:" + "c" * 64},
            "files": proof.inventory(self.payload), "native_files": ["llama-server", "libfixture.so"],
            "dependencies": {"internal": {}, "external": {}, "graph": {}}, "producer_probes": {},
        }
        proof.write(self.payload / "manifest.json", self.manifest)
        self.anchor = proof.sha(self.payload / "manifest.json")

    def verify(self, payload=None, anchor=None):
        return proof.validate_payload(payload or self.payload, anchor or self.anchor, self.identity, self.host)

    def test_positive_transport_preserves_mode_and_checks_all_files(self):
        archive = self.root / "bundle.tar"
        archive.write_bytes(proof.build_layer(self.payload))
        restored = self.root / "restored"
        proof.safe_unpack(archive, restored, proof.sha(archive))
        self.assertEqual(self.verify(restored), self.manifest)
        self.assertEqual((restored / "bin/llama-server").stat().st_mode & 0o777, 0o755)

    def test_independent_source_flags_replay_and_integrity_mutants(self):
        results = proof.fault_controls(self.payload, self.anchor, self.identity, self.host)
        self.assertEqual(len(results), 9)
        self.assertEqual(set(results.values()), {"REJECTED"})
        self.assertEqual(self.verify(), self.manifest)

    def test_transport_corruption_is_rejected_before_extraction(self):
        archive = self.root / "bundle.tar"
        archive.write_bytes(proof.build_layer(self.payload))
        digest = proof.sha(archive)
        raw = bytearray(archive.read_bytes())
        raw[0] ^= 1
        archive.write_bytes(raw)
        target = self.root / "must-not-exist"
        with self.assertRaisesRegex(ValueError, "transport_digest"):
            proof.safe_unpack(archive, target, digest)
        self.assertFalse(target.exists())

    def test_archive_paths_links_and_duplicate_members_rejected(self):
        for name, link, duplicate in (("artifact/../../escape", False, False),
                                      ("artifact/link", True, False),
                                      ("artifact/file", False, True)):
            with self.subTest(name=name):
                archive = self.root / "malformed.tar"
                with tarfile.open(archive, "w") as bundle:
                    row = tarfile.TarInfo(name)
                    row.mode = 0o644
                    if link:
                        row.type = tarfile.SYMTYPE
                        row.linkname = "/tmp/external"
                    else:
                        row.size = 1
                    bundle.addfile(row, None if link else io.BytesIO(b"x"))
                    if duplicate:
                        bundle.addfile(row, io.BytesIO(b"x"))
                with self.assertRaises(ValueError):
                    proof.safe_unpack(archive, self.root / "target", proof.sha(archive))
                self.assertFalse((self.root / "target").exists())

    def test_unknown_extra_file_and_changed_permissions_rejected(self):
        extra = self.payload / "unexpected"
        extra.write_text("extra")
        with self.assertRaisesRegex(ValueError, "unexpected_payload"):
            self.verify()
        extra.unlink()
        (self.payload / "bin/llama-server").chmod(0o644)
        with self.assertRaisesRegex(ValueError, "payload_mode"):
            self.verify()

    def test_internal_dependency_resolution_has_real_file_identity(self):
        target = self.payload / "bin/libfixture.so"
        text = f"linux-vdso.so.1 (0xffff)\nlibfixture.so => {target} (0x1234)\n"
        self.assertEqual(proof.parse_ldd(text), {"libfixture.so": target.resolve()})
        with self.assertRaisesRegex(ValueError, "unresolved_dependency:libmissing.so"):
            proof.parse_ldd("libmissing.so => not found\n")

    def test_missing_toolchain_or_changed_effective_flags_cannot_be_self_rehashed(self):
        altered = copy.deepcopy(self.manifest)
        altered["build"]["effective"]["GGML_NATIVE"] = "ON"
        proof.write(self.payload / "manifest.json", altered)
        with self.assertRaisesRegex(ValueError, "build_contract"):
            self.verify(anchor=proof.sha(self.payload / "manifest.json"))


if __name__ == "__main__":
    unittest.main()
