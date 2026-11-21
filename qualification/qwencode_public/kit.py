#!/usr/bin/env python3
"""Public-only, stdlib Qwen Code standalone artifact verifier/kit builder.
No private repositories, credentials, model endpoints or host identifiers.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "release-manifest.json"
ALLOWED_HOST = "github.com"


def load_manifest(path: Path = MANIFEST) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    assert obj["schema"] == "qwencode-public-release/v1"
    assert obj["upstream"] == "QwenLM/qwen-code"
    assert obj["upstream_ref"] == "v" + obj["version"]
    for item in obj["platforms"].values():
        assert len(item["sha256"]) == 64
        assert item["asset"].startswith("qwen-code-")
        assert item["format"] in ("zip", "tar.gz")
        assert item["size_bytes"] > 1_000_000
    return obj


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def checked_member(name: str) -> str:
    if not name or "\\" in name or "\x00" in name:
        raise ValueError("invalid archive member")
    path = PurePosixPath(name.rstrip("/"))
    if path.is_absolute() or not path.parts or any(x in ("..", ".", "") for x in path.parts):
        raise ValueError("archive path traversal")
    if ":" in path.parts[0]:
        raise ValueError("archive member drive prefix")
    return str(path)


def check_archive(path: Path, fmt: str, max_bytes: int = 700_000_000) -> None:
    names = set()
    total = 0
    if fmt == "zip":
        with zipfile.ZipFile(path, "r") as z:
            items = ((m.filename, m.file_size, (m.external_attr >> 16) & 0o170000,
                      m.is_dir()) for m in z.infolist())
            for name, size, mode, is_dir in items:
                safe = checked_member(name)
                if safe.casefold() in names:
                    raise ValueError("case-insensitive duplicate member")
                names.add(safe.casefold())
                if mode == stat.S_IFLNK:
                    raise ValueError("symlink archive entry")
                total += size
                if total > max_bytes:
                    raise ValueError("archive expanded size exceeds bound")
    elif fmt == "tar.gz":
        with tarfile.open(path, "r:gz") as t:
            for m in t:
                safe = checked_member(m.name)
                if safe.casefold() in names:
                    raise ValueError("case-insensitive duplicate member")
                names.add(safe.casefold())
                if not (m.isfile() or m.isdir()):
                    raise ValueError("non-regular archive entry")
                total += m.size
                if total > max_bytes:
                    raise ValueError("archive expanded size exceeds bound")
    else:
        raise ValueError("archive type not admitted")


def verify(path: Path, entry: dict) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size != entry["size_bytes"]:
        raise ValueError("download size mismatch")
    digest = checksum(path)
    if digest != entry["sha256"]:
        raise ValueError("download digest mismatch")
    check_archive(path, entry["format"])
    return {"sha256": digest, "bytes": size, "format": entry["format"], "archive_safe": True}


def download(manifest: dict, platform_id: str, output: Path) -> dict:
    entry = manifest["platforms"][platform_id]
    url = f'https://github.com/{manifest["upstream"]}/releases/download/{manifest["upstream_ref"]}/{entry["asset"]}'
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file():
        try:
            return verify(output, entry)
        except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError):
            output.unlink()
    # Downloads happen only inside disposable public GitHub Actions runners.
    # Exact digest is verified before an archive is ever extracted.
    error = None
    for attempt in range(3):
        tmp = output.with_name(output.name + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "qwencode-public-capsule/1"})
            with urllib.request.urlopen(req, timeout=50) as response, tmp.open("wb") as handle:
                # GitHub release redirects must remain on HTTPS.
                if response.url.split(":", 1)[0] != "https":
                    raise ValueError("insecure artifact redirect")
                shutil.copyfileobj(response, handle, 1024 * 1024)
            tmp.replace(output)
            return verify(output, entry)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            error = exc
            tmp.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
            time.sleep(min(2 ** attempt, 4))
    raise RuntimeError("pinned download failed: " + type(error).__name__)


def extract(path: Path, fmt: str, dst: Path) -> None:
    check_archive(path, fmt)
    dst.mkdir(parents=True, exist_ok=True)
    if fmt == "zip":
        with zipfile.ZipFile(path, "r") as z:
            z.extractall(dst)
    elif fmt == "tar.gz":
        with tarfile.open(path, "r:gz") as t:
            for m in t:
                # All entries already validated as regular files/directories.
                target = dst / checked_member(m.name)
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with t.extractfile(m) as source, target.open("wb") as out:
                        shutil.copyfileobj(source, out)
                    target.chmod(m.mode & 0o755 or 0o644)


def smoke(manifest: dict, platform_id: str, archive: Path, root: Path) -> dict:
    entry = manifest["platforms"][platform_id]
    verify(archive, entry)
    extract(archive, entry["format"], root)
    executable = root / entry["binary"]
    if not executable.exists():
        raise ValueError("entrypoint missing")
    if platform_id.startswith("windows"):
        args = ["cmd.exe", "/d", "/c", str(executable), "--version"]
    else:
        args = [str(executable), "--version"]
    result = subprocess.run(args, capture_output=True, text=True, timeout=45,
                            cwd=str(root), env={**os.environ, "CI": "true"})
    if result.returncode != 0 or manifest["version"] not in result.stdout + result.stderr:
        raise RuntimeError("native qwen version check failed")
    return {"version": manifest["version"], "native_cli": "PASS", "platform": platform_id}


def add_file(z: zipfile.ZipFile, arc: str, content: bytes, stored: bool = False) -> None:
    info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    z.writestr(info, content)


def assemble(manifest: dict, platform_id: str, archive: Path, output: Path) -> dict:
    entry = manifest["platforms"][platform_id]
    verify(archive, entry)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "qwencode-public-kit/v1",
        "platform": platform_id,
        "upstream": manifest["upstream"],
        "version": manifest["version"],
        "source_ref": manifest["upstream_ref"],
        "asset": entry["asset"],
        "sha256": entry["sha256"],
        "size_bytes": entry["size_bytes"],
        "classification": "public-synthetic",
        "authority": "NO_PRODUCTION_ADMISSION"
    }
    with zipfile.ZipFile(output, "w", allowZip64=True) as z:
        add_file(z, "kit.json", (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode())
        for name in ("Invoke-QwenCapsule.ps1", "README.md", "release-manifest.json"):
            add_file(z, name, (HERE / name).read_bytes())
        add_file(z, "upstream/" + entry["asset"], archive.read_bytes(), stored=True)
    return {"kit_sha256": checksum(output), "kit_bytes": output.stat().st_size,
            "source_sha256": entry["sha256"], "classification": "PUBLIC_SYNTHETIC_BUILD"}


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="qwen-public-test-") as td:
        root = Path(td)
        safe = root / "safe.zip"
        with zipfile.ZipFile(safe, "w") as z:
            z.writestr("qwen-code/file.txt", "test")
        check_archive(safe, "zip")
        for bad in ("../escape", "C:/escape", "/rooted", "a/../../escape"):
            path = root / "bad.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr(bad, "bad")
            try:
                check_archive(path, "zip")
            except ValueError:
                pass
            else:
                raise AssertionError("unsafe ZIP member admitted")
        dupe = root / "dupe.zip"
        with zipfile.ZipFile(dupe, "w") as z:
            z.writestr("qwen/a", "1")
            z.writestr("QWEN/A", "2")
        try:
            check_archive(dupe, "zip")
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate accepted")
        bad_tgz = root / "symlink.tar.gz"
        with tarfile.open(bad_tgz, "w:gz") as t:
            m = tarfile.TarInfo("qwen-code/link")
            m.type = tarfile.SYMTYPE
            m.linkname = "/etc/passwd"
            t.addfile(m)
        try:
            check_archive(bad_tgz, "tar.gz")
        except ValueError:
            pass
        else:
            raise AssertionError("tar symlink accepted")
        expected = {"size_bytes": safe.stat().st_size, "sha256": "f" * 64, "format": "zip"}
        try:
            verify(safe, expected)
        except ValueError:
            pass
        else:
            raise AssertionError("wrong hash accepted")
    print("PASS standard-library synthetic archive/hash/fault tests")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("self-test", "fetch", "smoke", "assemble"))
    parser.add_argument("--platform", choices=("windows-x64", "linux-x64"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--out", type=Path)
    ns = parser.parse_args()
    manifest = load_manifest()
    if ns.action == "self-test":
        self_test()
        return
    if not ns.platform or not ns.archive:
        parser.error("platform and archive required")
    if ns.action == "fetch":
        row = download(manifest, ns.platform, ns.archive)
    elif ns.action == "smoke":
        if not ns.out:
            parser.error("smoke requires --out")
        row = smoke(manifest, ns.platform, ns.archive, ns.out)
    else:
        if not ns.out:
            parser.error("assemble requires --out")
        row = assemble(manifest, ns.platform, ns.archive, ns.out)
    print(json.dumps(row, sort_keys=True))


if __name__ == "__main__":
    main()
