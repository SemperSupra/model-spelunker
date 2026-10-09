import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod

PACK = load("package_artifact_oci", HERE / "package_artifact_oci.py")
HYDRATE = load("hydrate_oci_layout", HERE / "hydrate_oci_layout.py")


class OciPackerTests(unittest.TestCase):
    def make_payload(self, root: Path):
        payload = root / "payload"
        (payload / "wheelhouse").mkdir(parents=True)
        (payload / "build-receipt.json").write_text('{"x":1}\n', encoding="utf-8")
        exe = payload / "tool"
        exe.write_bytes(b"#!/bin/sh\necho ok\n")
        exe.chmod(0o755)
        (payload / "wheelhouse" / "a.whl").write_bytes(b"wheel")
        return payload

    def test_reproducible_across_mtime_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self.make_payload(root)

            layout1 = root / "oci1"
            first = PACK.package(payload, layout1, "artifact", "amd64", "linux")

            for path in payload.rglob("*"):
                if path.exists():
                    os.utime(path, (2000000000, 2000000000))

            layout2 = root / "oci2"
            second = PACK.package(payload, layout2, "artifact", "amd64", "linux")

            self.assertEqual(first["manifest_digest"], second["manifest_digest"])
            self.assertEqual(first["layer_digest"], second["layer_digest"])
            self.assertEqual(first["config_digest"], second["config_digest"])

    def test_existing_hydrator_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self.make_payload(root)
            layout = root / "oci"
            result = PACK.package(payload, layout, "artifact", "amd64", "linux")

            hydrated = root / "hydrated"
            summary = HYDRATE.hydrate(layout, hydrated, "artifact")

            self.assertEqual(summary["manifest_digest"], result["manifest_digest"])
            self.assertEqual(
                (hydrated / "artifact" / "build-receipt.json").read_text(),
                '{"x":1}\n',
            )
            self.assertEqual(
                (hydrated / "artifact" / "wheelhouse" / "a.whl").read_bytes(),
                b"wheel",
            )
            self.assertTrue((hydrated / "artifact" / "tool").stat().st_mode & 0o111)

    def test_rejects_symlink(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink unsupported")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = root / "payload"
            payload.mkdir()
            target = payload / "target"
            target.write_text("x", encoding="utf-8")
            link = payload / "link"
            try:
                link.symlink_to(target.name)
            except OSError:
                self.skipTest("symlink unavailable")
            with self.assertRaises(ValueError):
                PACK.package(payload, root / "oci", "artifact", "amd64", "linux")


if __name__ == "__main__":
    unittest.main()
