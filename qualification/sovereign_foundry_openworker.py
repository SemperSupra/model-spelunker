#!/usr/bin/env python3
"""Rootless OpenWorker foundry: observe -> plan -> build -> verify -> publish -> admit.

The OCI image is an inert distribution envelope, not a runtime. Never use sudo,
Docker, a global pip install, or an unpinned upstream source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile

from qualification.hydrate_oci_layout import hydrate
from qualification.package_artifact_oci import package
from qualification.verify_hydrated_artifact import verify as verify_payload

SOURCE = "https://github.com/andrewyng/openworker.git"
SOURCE_SHA = "5bc10d928e0b64aae74313349a3b17bd19643ae2"
REGCTL_VERSION = "v0.11.6"
REGCTL_SHA256 = "8e0e62a497fcdb8048d18aa927a139613176ba0531f412bc541044e28f9856bd"
IMAGE = "ghcr.io/sempersupra/model-spelunker-harness-openworker"
RECIPE = "openworker-wheelhouse-sovereign-python-abi-v1"
PROFILE_REF = "qualification/harness-realizations/openworker-linux-amd64-sovereign-python-abi-v1.json"


def realization_binding() -> dict:
    profile = json.loads((Path(__file__).resolve().parents[1] / PROFILE_REF).read_text(encoding="utf-8"))
    if profile["harness"]["name"] != "openworker" or profile["harness"]["source_revision"] != SOURCE_SHA:
        raise ValueError("realization profile source mismatch")
    if profile["build"]["recipe_id"] != RECIPE:
        raise ValueError("realization profile recipe mismatch")
    payload = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"profile_ref": PROFILE_REF, "profile_digest": sha(payload)}


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return "sha256:" + h.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def run(args: list[str], *, cwd: Path | None = None, input_stream=None) -> str:
    # Command arguments are controlled constants or paths; NEVER put tokens here.
    p = subprocess.run(args, cwd=cwd, stdin=input_stream, capture_output=True, text=True, check=False)
    if p.returncode:
        raise RuntimeError("bounded step failed: " + Path(args[0]).name + " rc=" + str(p.returncode))
    return p.stdout.strip()


def generic_requirements() -> dict:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("this realization requires Linux x86_64")
    for name in ("git", "gh", "uv"):
        if not shutil.which(name):
            raise ValueError("missing user-accessible command: " + name)
    return {
        "target": "linux-x86_64-python3",
        "python_version": platform.python_version(),
        "python_abi": sysconfig.get_config_var("SOABI") or "unknown",
        "git_available": True,
        "gh_available": True,
        "uv_available": True,
        "source_revision": SOURCE_SHA,
        "recipe": RECIPE,
        "privileged_runtime_required": False,
    }


def preview() -> dict:
    info = generic_requirements()
    return {
        "schema": "model-spelunker.sovereign-foundry-plan.v1",
        "status": "READY",
        "facts": info,
        "steps": ["clone-pinned-source", "create-user-venv", "build-wheelhouse",
                  "receipt-and-offline-import", "package-oci-layout",
                  "verify-local-payload", "publish-explicit", "admit-refetched-digest"],
        "publish_requires": "gh write:packages (explicit separate operation)",
        "performance_qualification": "NOT_PERFORMED",
    }


def make_venv(venv: Path) -> Path:
    # uv works on TrueNAS even when ensurepip/pip is absent from system Python.
    run(["uv", "venv", "--python", sys.executable, str(venv)])
    python = venv / "bin" / "python"
    run(["uv", "pip", "install", "--python", str(python),
         "pip==25.2", "wheel==0.45.1", "build==1.3.0"])
    return python


def smoke_install(wheelhouse: Path, tmp: Path) -> None:
    venv = tmp / "smoke"
    run(["uv", "venv", "--python", sys.executable, str(venv)])
    python = venv / "bin" / "python"
    wheels = sorted(wheelhouse.glob("*.whl"))
    if not wheels:
        raise ValueError("empty wheelhouse")
    run(["uv", "pip", "install", "--python", str(python), "--offline",
         "--no-deps", *map(str, wheels)])
    run([str(python), "-c", "import coworker; import coworker.engine"])
    run([str(venv / "bin" / "openworker"), "--help"])


def verify_local(out: Path) -> dict:
    receipt_path = out / "payload" / "build-receipt.json"
    if not receipt_path.is_file():
        raise ValueError("missing local build receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["source"]["revision"] != SOURCE_SHA or receipt["build"]["recipe_id"] != RECIPE:
        raise ValueError("pinned source/recipe mismatch")
    if receipt["harness"]["name"] != "openworker":
        raise ValueError("harness identity mismatch")
    if receipt["build"].get("configuration", {}).get("realization") != realization_binding():
        raise ValueError("harness realization binding mismatch")
    for row in receipt["payload"]["files"]:
        rel = Path(row["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("unsafe receipt payload path")
        path = out / "payload" / rel
        if not path.is_file() or path.stat().st_size != row["bytes"]:
            raise ValueError("payload size mismatch")
        if digest_file(path) != "sha256:" + row["sha256"]:
            raise ValueError("payload digest mismatch")
    layout = out / "oci"
    with tempfile.TemporaryDirectory(prefix="foundry-local-verify-") as td:
        summary = hydrate(layout, Path(td), "artifact")
        if (Path(td) / "artifact" / "build-receipt.json").read_bytes() != receipt_path.read_bytes():
            raise ValueError("embedded build receipt mismatch")
        if summary["manifest_digest"] != json.loads((out / "layout-receipt.json").read_text())["manifest_digest"]:
            raise ValueError("OCI manifest mismatch")
        for row in receipt["payload"]["files"]:
            if digest_file(Path(td) / "artifact" / row["path"]) != "sha256:" + row["sha256"]:
                raise ValueError("hydrated payload mismatch")
    return {"state": "LOCAL_VERIFIED", "manifest_digest": summary["manifest_digest"],
            "payload_files": len(receipt["payload"]["files"]), "model_inference": False}


def build(out: Path) -> dict:
    if out.exists():
        return {**verify_local(out), "state": "ALREADY_BUILT"}
    facts = generic_requirements()
    if not out.parent.is_dir():
        raise ValueError("output parent must already exist")
    stage = Path(tempfile.mkdtemp(prefix=".foundry-openworker-", dir=out.parent))
    try:
        source = stage / "src"
        run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", SOURCE, str(source)])
        run(["git", "-C", str(source), "checkout", "--quiet", "--detach", SOURCE_SHA])
        if run(["git", "-C", str(source), "rev-parse", "HEAD"]) != SOURCE_SHA:
            raise ValueError("upstream source revision mismatch")
        python = make_venv(stage / "build-venv")
        payload = stage / "payload"
        wheels = payload / "wheelhouse"
        wheels.mkdir(parents=True)
        run([str(python), "-m", "pip", "wheel", "--disable-pip-version-check",
             "--no-input", "--wheel-dir", str(wheels), str(source)])
        files = []
        for wheel in sorted(wheels.glob("*.whl")):
            files.append({"path": "wheelhouse/" + wheel.name,
                          "sha256": digest_file(wheel).split(":", 1)[1],
                          "bytes": wheel.stat().st_size})
        if not files:
            raise ValueError("wheelhouse is empty")
        smoke_install(wheels, stage)
        build_receipt = {
            "schema_version": 1, "record_type": "harness-build-receipt",
            "harness": {"name": "openworker", "declared_version": "0.0.0"},
            "source": {"repository": SOURCE, "revision": SOURCE_SHA, "lockfile_digest": None},
            "build": {"recipe_id": RECIPE, "target": facts["target"],
                      "builder_class": "sovereign-linux-x86_64-userland",
                      "toolchain": "Python " + facts["python_version"] + "; uv; pip 25.2",
                      "configuration": {"python_abi": facts["python_abi"],
                                        "payload": "offline-wheelhouse",
                                        "compiler_flags": [],
                                        "no_root": True,
                                        "realization": realization_binding()}},
            "payload": {"kind": "python-wheelhouse", "files": files},
        }
        atomic_json(payload / "build-receipt.json", build_receipt)
        layout_receipt = package(payload, stage / "oci", "artifact", "amd64", "linux")
        atomic_json(stage / "layout-receipt.json", layout_receipt)
        verification = verify_local(stage)
        # Persist only the distribution payload and evidence, never the source
        # checkout or build/smoke environments.
        for disposable in ("src", "build-venv", "smoke"):
            path = stage / disposable
            if path.exists():
                shutil.rmtree(path)
        stage.rename(out)
        return {"state": "BUILT_AND_LOCAL_VERIFIED", **verification}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def regctl_path(tmp: Path) -> Path:
    tool = tmp / "regctl-linux-amd64"
    run(["gh", "release", "download", REGCTL_VERSION,
         "--repo", "regclient/regclient", "--pattern", "regctl-linux-amd64",
         "--dir", str(tmp), "--clobber"])
    if digest_file(tool) != "sha256:" + REGCTL_SHA256:
        raise ValueError("pinned regctl binary hash mismatch")
    tool.chmod(0o700)
    return tool


def registry_login(regctl: Path, config: Path) -> None:
    user = run(["gh", "api", "user", "--jq", ".login"])
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", user):
        raise ValueError("unexpected GitHub login")
    env = {**os.environ, "REGCTL_CONFIG": str(config)}
    token = subprocess.Popen(["gh", "auth", "token"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        login = subprocess.run([str(regctl), "registry", "login", "ghcr.io",
                                "-u", user, "--pass-stdin"], env=env,
                               stdin=token.stdout, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=False)
        if token.stdout:
            token.stdout.close()
        trc = token.wait()
        if trc or login.returncode:
            raise RuntimeError("GHCR authentication unavailable; check package scopes")
    finally:
        if token.poll() is None:
            token.kill()
            token.wait()


def registry_copy(regctl: Path, config: Path, src: str, dst: str) -> None:
    env = {**os.environ, "REGCTL_CONFIG": str(config)}
    result = subprocess.run([str(regctl), "image", "copy", src, dst],
                            env=env, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError("rootless OCI registry copy failed (credentials/permissions/transport)")


def image_digest(regctl: Path, config: Path, name: str) -> str | None:
    env = {**os.environ, "REGCTL_CONFIG": str(config)}
    result = subprocess.run([str(regctl), "image", "digest", name],
                            env=env, capture_output=True, text=True, check=False)
    if result.returncode:
        return None
    value = result.stdout.strip()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise ValueError("registry returned invalid manifest digest")
    return value


def admit_from_registry(regctl: Path, config: Path, immutable_ref: str,
                        expected: str, tmp: Path) -> dict:
    layout = tmp / "remote-oci"
    registry_copy(regctl, config, immutable_ref, "ocidir://" + str(layout) + ":artifact")
    root = tmp / "remote-hydrated"
    summary = hydrate(layout, root, "artifact")
    if summary["manifest_digest"] != expected:
        raise ValueError("fetched OCI manifest drift")
    build_receipt = root / "artifact" / "build-receipt.json"
    if not build_receipt.is_file():
        raise ValueError("published artifact omitted build receipt")
    embedded = json.loads(build_receipt.read_text(encoding="utf-8"))
    if embedded["source"]["revision"] != SOURCE_SHA:
        raise ValueError("published source identity mismatch")
    admission = {
        "schema_version": 1, "record_type": "harness-artifact-admission",
        "harness": embedded["harness"],
        "artifact": {"packaging": "oci-distribution", "ref": immutable_ref,
                     "digest": expected, "build_receipt_digest": digest_file(build_receipt)},
        "admission": {"state": "BUILD_ADMITTED",
                      "target": embedded["build"]["target"],
                      "checks": [
                          {"name": "manifest-digest", "result": "PASS"},
                          {"name": "embedded-build-receipt", "result": "PASS"},
                          {"name": "payload-hashes", "result": "PASS"},
                          {"name": "offline-wheelhouse-install-no-resolve", "result": "PASS"},
                          {"name": "coworker-import-and-cli", "result": "PASS"},
                      ]},
    }
    verify_payload(root, admission, expected)
    smoke_install(root / "artifact" / "wheelhouse", tmp)
    return admission


def publish(out: Path, *, registry_image: str) -> dict:
    verified = verify_local(out)
    if not re.fullmatch(r"ghcr\.io/[a-z0-9-]+/[a-z0-9._-]+", registry_image):
        raise ValueError("registry_image must be a fully qualified GHCR package (no tag)")
    expected = verified["manifest_digest"]
    tag = "src-" + SOURCE_SHA[:12] + "-abi-" + expected.split(":")[1][:16]
    destination = registry_image + ":" + tag
    with tempfile.TemporaryDirectory(prefix="model-spelunker-publish-") as td:
        tmp = Path(td)
        tmp.chmod(0o700)
        regctl = regctl_path(tmp)
        cfg = tmp / "regctl.json"
        registry_login(regctl, cfg)
        prior = image_digest(regctl, cfg, destination)
        if prior and prior != expected:
            raise ValueError("refusing to overwrite a tag pointing at a different digest")
        if not prior:
            registry_copy(regctl, cfg, "ocidir://" + str(out / "oci") + ":artifact", destination)
        observed = image_digest(regctl, cfg, destination)
        if observed != expected:
            raise ValueError("published OCI manifest digest mismatch")
        immutable_ref = registry_image + "@" + expected
        admission = admit_from_registry(regctl, cfg, immutable_ref, expected, tmp)
    atomic_json(out / "admission.json", admission)
    result = {"state": "BUILD_ADMITTED", "artifact_ref": immutable_ref,
              "manifest_digest": expected, "harness_realization": realization_binding(),
              "model_inference": False}
    atomic_json(out / "publication.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["observe", "plan", "build", "verify", "publish"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--registry-image", default=IMAGE)
    args = parser.parse_args()
    try:
        if args.phase == "observe":
            result = generic_requirements()
        elif args.phase == "plan":
            result = preview()
        else:
            if args.output is None:
                parser.error("--output is required for build/verify/publish")
            out = args.output.expanduser().absolute()
            if args.phase == "build":
                result = build(out)
            elif args.phase == "verify":
                result = verify_local(out)
            else:
                result = publish(out, registry_image=args.registry_image)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (RuntimeError, ValueError, OSError, KeyError) as exc:
        # Exception messages here must never interpolate credentials.
        print("FOUNDRY_BLOCKED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
