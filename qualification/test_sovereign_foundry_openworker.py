"""Hermetic foundry contract tests: no GitHub network, compiler, credentials or Docker."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from qualification import sovereign_foundry_openworker as foundry


class FoundryTests(unittest.TestCase):
    def fixture(self, root: Path):
        out = root / "build"
        (out / "payload" / "wheelhouse").mkdir(parents=True)
        wheel = out / "payload" / "wheelhouse" / "example-0.1-py3-none-any.whl"
        wheel.write_bytes(b"example wheel")
        receipt = {
            "schema_version": 1, "record_type": "harness-build-receipt",
            "harness": {"name": "openworker", "declared_version": "0.0.0"},
            "source": {"repository": foundry.SOURCE, "revision": foundry.SOURCE_SHA, "lockfile_digest": None},
            "build": {"recipe_id": foundry.RECIPE, "target": "linux-x86_64-python3",
                      "builder_class": "test", "toolchain": "python-test", "configuration": {}},
            "payload": {"kind": "python-wheelhouse", "files": [
                {"path": "wheelhouse/" + wheel.name,
                 "sha256": foundry.digest_file(wheel).split(":")[1],
                 "bytes": wheel.stat().st_size}]},
        }
        foundry.atomic_json(out / "payload" / "build-receipt.json", receipt)
        layout = foundry.package(out / "payload", out / "oci", "artifact", "amd64", "linux")
        foundry.atomic_json(out / "layout-receipt.json", layout)
        return out, layout["manifest_digest"]

    def test_local_roundtrip_and_no_absolute_builder_path(self):
        with tempfile.TemporaryDirectory() as td:
            out, expected = self.fixture(Path(td))
            observed = foundry.verify_local(out)
            self.assertEqual(observed["manifest_digest"], expected)
            self.assertEqual(observed["payload_files"], 1)
            self.assertNotIn(str(out), (out / "layout-receipt.json").read_text())

    def test_modified_payload_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out, _ = self.fixture(Path(td))
            (out / "payload" / "wheelhouse" / "example-0.1-py3-none-any.whl").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "size mismatch|digest mismatch"):
                foundry.verify_local(out)

    def test_modified_oci_layer_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out, _ = self.fixture(Path(td))
            layout = json.loads((out / "layout-receipt.json").read_text())
            layer = out / "oci" / "blobs" / "sha256" / layout["layer_digest"].split(":")[1]
            layer.write_bytes(b"bad layer")
            with self.assertRaises(ValueError):
                foundry.verify_local(out)

    def test_wrong_source_ref_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out, _ = self.fixture(Path(td))
            p = out / "payload" / "build-receipt.json"
            doc = json.loads(p.read_text())
            doc["source"]["revision"] = "0" * 40
            foundry.atomic_json(p, doc)
            with self.assertRaisesRegex(ValueError, "source/recipe mismatch"):
                foundry.verify_local(out)

    def test_refuses_overwrite_of_existing_different_remote_tag(self):
        with tempfile.TemporaryDirectory() as td:
            out, _ = self.fixture(Path(td))
            with mock.patch.object(foundry, "regctl_path", return_value=Path("/ignored")), \
                 mock.patch.object(foundry, "registry_login"), \
                 mock.patch.object(foundry, "image_digest", return_value="sha256:" + "0" * 64):
                with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                    foundry.publish(out, registry_image=foundry.IMAGE)

    def test_publication_roundtrip_and_idempotence(self):
        with tempfile.TemporaryDirectory() as td:
            out, digest = self.fixture(Path(td))
            copy_requests = []
            state = {"remote": None}
            def fake_copy(tool, config, src, dst):
                copy_requests.append((src, dst))
                if src.startswith("ocidir://"):
                    state["remote"] = digest
                else:
                    source_layout = out / "oci"
                    path = Path(dst.removeprefix("ocidir://").rsplit(":", 1)[0])
                    import shutil
                    shutil.copytree(source_layout, path)

            def fake_digest(tool, config, name):
                return state["remote"]

            with mock.patch.object(foundry, "regctl_path", return_value=Path("/ignored")), \
                 mock.patch.object(foundry, "registry_login"), \
                 mock.patch.object(foundry, "registry_copy", side_effect=fake_copy), \
                 mock.patch.object(foundry, "image_digest", side_effect=fake_digest), \
                 mock.patch.object(foundry, "smoke_install"):
                first = foundry.publish(out, registry_image=foundry.IMAGE)
                second = foundry.publish(out, registry_image=foundry.IMAGE)

            self.assertEqual(first["state"], "BUILD_ADMITTED")
            self.assertEqual(first, second)
            self.assertEqual(first["artifact_ref"], foundry.IMAGE + "@" + digest)
            # Only the first publication writes a tag; second rechecks/re-admits.
            self.assertEqual(sum(src.startswith("ocidir://") for src, _ in copy_requests), 1)
            self.assertEqual(json.loads((out / "admission.json").read_text())["admission"]["state"], "BUILD_ADMITTED")

    def test_publish_refuses_unknown_registry_image(self):
        with tempfile.TemporaryDirectory() as td:
            out, _ = self.fixture(Path(td))
            with self.assertRaisesRegex(ValueError, "fully qualified GHCR"):
                foundry.publish(out, registry_image="docker.io/outside/image")

    def test_build_is_idempotent_without_toolchain_or_network(self):
        with tempfile.TemporaryDirectory() as td:
            out, digest = self.fixture(Path(td))
            with mock.patch.object(foundry, "generic_requirements", side_effect=AssertionError("must not rebuild")):
                result = foundry.build(out)
            self.assertEqual(result["state"], "ALREADY_BUILT")
            self.assertEqual(result["manifest_digest"], digest)


if __name__ == "__main__":
    unittest.main()
