#!/usr/bin/env python3
"""Same-substrate reuse proof for one pinned native llama.cpp CPU build.

Uses the repository's existing deterministic tar layer builder. This is a
three-job public experiment, not an artifact registry or deployment mechanism.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from qualification.package_artifact_oci import build_layer, normalized_mode

REV = "a6ac41c757c066941766164439f6876f2deaab04"
UPSTREAM = "https://github.com/ggml-org/llama.cpp.git"
FLAGS = ["-DCMAKE_BUILD_TYPE=Release", "-DGGML_NATIVE=OFF",
         "-DLLAMA_BUILD_TESTS=OFF", "-DLLAMA_BUILD_EXAMPLES=OFF", "-DLLAMA_BUILD_SERVER=ON"]
EFFECTIVE = {flag[2:].split("=", 1)[0]: flag.split("=", 1)[1] for flag in FLAGS}
SCHEMA = "native-build-reuse-r0/v1"
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(path):
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def digest_ok(value):
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def command(args, *, env=None, cwd=None, timeout=60, log=None):
    started = time.monotonic()
    result = subprocess.run(args, env=env, cwd=cwd, timeout=timeout, capture_output=True)
    elapsed = time.monotonic() - started
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(result.stdout + result.stderr)
    require(result.returncode == 0, "command_failed:" + Path(args[0]).name)
    return result.stdout.decode(errors="replace"), result.stderr.decode(errors="replace"), elapsed


def environment(bin_dir=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("LD_")}
    if bin_dir is not None:
        env["LD_LIBRARY_PATH"] = str(bin_dir.resolve())
    return env


def substrate():
    release = platform.freedesktop_os_release()
    return {"system": platform.system(), "machine": platform.machine(),
            "os_id": release["ID"], "os_version": release["VERSION_ID"],
            "libc": list(platform.libc_ver()), "image_os": os.environ.get("ImageOS"),
            "image_version": os.environ.get("ImageVersion")}


def expected_identity():
    value = {"repository": os.environ["GITHUB_REPOSITORY"],
             "source_commit": os.environ["GITHUB_SHA"], "run_id": os.environ["GITHUB_RUN_ID"],
             "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"]}
    require(value["repository"] == "SemperSupra/model-spelunker", "repository_identity")
    require(re.fullmatch("[0-9a-f]{40}", value["source_commit"]) is not None, "project_source_identity")
    require(value["run_id"].isdigit() and value["run_attempt"].isdigit(), "run_identity")
    return value


def cache_values(path):
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith(("//", "#")) or ":" not in line or "=" not in line:
            continue
        key = line.split(":", 1)[0]
        values[key] = line.split("=", 1)[1]
    return values


def tool_identity(path):
    path = Path(path).resolve()
    stdout, stderr, _ = command([str(path), "--version"])
    text = (stdout + stderr).strip()
    require(text, "missing_tool_version")
    return {"path": str(path), "sha256": sha(path), "version": text[:4096]}


def parse_ldd(text):
    found = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("linux-vdso."):
            continue
        if "not found" in line:
            name = line.split("=>", 1)[0].strip()
            name = name if re.fullmatch(r"[A-Za-z0-9_.+-]{1,120}", name) else "unknown"
            raise ValueError("unresolved_dependency:" + name)
        if "=>" in line:
            name, target = (part.strip() for part in line.split("=>", 1))
        else:
            target = line
            name = Path(target.split(" (", 1)[0]).name
        target = target.split(" (", 1)[0].strip()
        require(target.startswith("/"), "unrecognized_dependency_resolution")
        path = Path(target).resolve()
        require(path.is_file(), "missing_resolved_dependency")
        require(name not in found or found[name] == path, "conflicting_dependency_resolution")
        found[name] = path
    require(found, "empty_dynamic_dependency_set")
    return found


def dependencies(bin_dir, names, evidence=None):
    """Resolve every packaged native object, retaining exact external identities."""
    internal, external, graph = {}, {}, {}
    for name in names:
        stdout, stderr, _ = command(["ldd", str(bin_dir / name)], env=environment(bin_dir),
                                   log=evidence / (name + ".txt") if evidence else None)
        entries = parse_ldd(stdout + stderr)
        graph[name] = sorted(entries)
        for soname, path in entries.items():
            record = {"sha256": sha(path), "bytes": path.stat().st_size}
            if path.is_relative_to(bin_dir.resolve()):
                require((bin_dir / soname).is_file(), "missing_internal_soname")
                require(sha(bin_dir / soname) == record["sha256"], "internal_resolution_alias")
                target = internal
            else:
                target = external
            require(soname not in target or target[soname] == record, "dependency_identity_conflict")
            target[soname] = record
    return {"internal": internal, "external": external, "graph": graph}


def probes(bin_dir, evidence):
    outputs = {}
    for flag, name in (("--version", "version"), ("--help", "help")):
        stdout, stderr, elapsed = command(
            [str(bin_dir / "llama-server"), flag], env=environment(bin_dir), timeout=30)
        (evidence / (name + ".stdout.txt")).write_text(stdout)
        (evidence / (name + ".stderr.txt")).write_text(stderr)
        combined = stdout + stderr
        if name == "version":
            require(REV[:7] in combined, "native_version_source_mismatch")
        else:
            require("--model" in combined and "--host" in combined, "native_help_surface")
        outputs[name] = {"exit_code": 0, "wall_s": elapsed,
                         "stdout_sha256": "sha256:" + hashlib.sha256(stdout.encode()).hexdigest(),
                         "stderr_sha256": "sha256:" + hashlib.sha256(stderr.encode()).hexdigest(),
                         "stdout_bytes": len(stdout.encode()), "stderr_bytes": len(stderr.encode())}
    return outputs


def inventory(payload):
    return [{"path": path.relative_to(payload).as_posix(), "sha256": sha(path),
             "bytes": path.stat().st_size, "mode": normalized_mode(path)}
            for path in sorted(payload.rglob("*")) if path.is_file()]


def safe_unpack(archive_path, destination, expected_sha):
    require(digest_ok(expected_sha) and sha(archive_path) == expected_sha, "transport_digest")
    require(archive_path.stat().st_size <= MAX_ARCHIVE_BYTES, "archive_size")
    require(not destination.exists(), "extraction_destination_exists")
    with tarfile.open(archive_path, "r:") as archive:
        members = archive.getmembers()
        require(0 < len(members) <= 256, "archive_member_count")
        seen, total = set(), 0
        for member in members:
            path = PurePosixPath(member.name)
            require(path.parts and path.parts[0] == "artifact" and
                    member.name == path.as_posix() and not path.is_absolute() and
                    ".." not in path.parts and "\\" not in member.name, "unsafe_archive_path")
            require(member.name not in seen, "duplicate_archive_member")
            seen.add(member.name)
            require(member.isdir() or member.isfile(), "unsupported_archive_member")
            require(member.mode in (0o644, 0o755), "archive_mode")
            total += member.size
        require(total <= MAX_ARCHIVE_BYTES, "expanded_archive_size")
        destination.mkdir()
        # Explicit regular-file extraction; no links, devices, ownership or
        # archive-controlled root paths are passed to tarfile.extractall.
        for member in members:
            relative = PurePosixPath(member.name).parts[1:]
            path = destination.joinpath(*relative)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, path.open("xb") as target:
                    shutil.copyfileobj(source, target)
                path.chmod(member.mode)


def validate_payload(payload, manifest_sha, expected, current_platform):
    manifest_path = payload / "manifest.json"
    require(digest_ok(manifest_sha) and sha(manifest_path) == manifest_sha, "manifest_digest")
    manifest = json.loads(manifest_path.read_bytes())
    require(manifest["schema"] == SCHEMA and manifest["scope"] == "SAME_SUBSTRATE_CLI_ONLY", "manifest_scope")
    require(manifest["producer"] == expected, "producer_or_replay_mismatch")
    require(manifest["upstream"] == {"url": UPSTREAM, "revision": REV}, "upstream_identity")
    require(manifest["platform"] == current_platform, "substrate_mismatch")
    require(current_platform["system"] == "Linux" and current_platform["machine"] == "x86_64" and
            current_platform["os_id"] == "ubuntu" and current_platform["os_version"] == "24.04",
            "target_platform")
    build = manifest["build"]
    require(build["flags"] == FLAGS and build["effective"] == EFFECTIVE and
            build["parallel_jobs"] == 2, "build_contract")
    for name in ("c_compiler", "cxx_compiler", "cmake", "linker"):
        item = build["toolchain"].get(name, {})
        require(digest_ok(item.get("sha256")) and bool(item.get("version")), "toolchain_provenance")
    require(digest_ok(build["cmake_cache_sha256"]), "cmake_cache_identity")
    files, seen = manifest["files"], set()
    require(isinstance(files, list) and files, "empty_payload")
    for row in files:
        relative = PurePosixPath(row["path"])
        require(relative.parts and not relative.is_absolute() and ".." not in relative.parts and
                relative.as_posix() == row["path"] and "\\" not in row["path"], "payload_path")
        require(row["path"] not in seen and row["path"] != "manifest.json", "duplicate_payload_path")
        seen.add(row["path"])
        path = payload / row["path"]
        require(path.is_file() and not path.is_symlink(), "missing_or_linked_payload")
        require(type(row["bytes"]) is int and row["bytes"] == path.stat().st_size and
                digest_ok(row["sha256"]) and sha(path) == row["sha256"], "payload_integrity")
        require(stat.S_IMODE(path.stat().st_mode) == row["mode"] and row["mode"] in (0o644, 0o755),
                "payload_mode")
    actual = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
    require(actual == seen | {"manifest.json"}, "unexpected_payload")
    require(not any(p.is_symlink() for p in payload.rglob("*")), "linked_payload_entry")
    names = manifest["native_files"]
    require(isinstance(names, list) and names and names[0] == "llama-server" and len(set(names)) == len(names),
            "native_file_declaration")
    require(all("bin/" + name in seen and Path(name).name == name for name in names), "native_file_binding")
    require(any(".so" in name for name in names), "missing_project_shared_libraries")
    return manifest


def fault_controls(payload, manifest_sha, expected, current_platform):
    """Mutants are rejected by the consumer verifier before any native command."""
    cases = {}
    def reject(name, root, anchor, identity, host):
        try:
            validate_payload(root, anchor, identity, host)
        except (ValueError, FileNotFoundError, KeyError):
            cases[name] = "REJECTED"
        else:
            raise AssertionError("fault_accepted:" + name)
    wrong = dict(expected, run_id=str(int(expected["run_id"]) + 1))
    reject("different_run_replay", payload, manifest_sha, wrong, current_platform)
    wrong = dict(expected, run_attempt=str(int(expected["run_attempt"]) + 1))
    reject("different_attempt_replay", payload, manifest_sha, wrong, current_platform)
    reject("wrong_manifest_anchor", payload, "sha256:" + "0"*64, expected, current_platform)
    reject("different_substrate", payload, manifest_sha, expected, dict(current_platform, os_version="22.04"))
    original = json.loads((payload / "manifest.json").read_bytes())
    for name in ("wrong_upstream", "changed_flags", "missing_toolchain", "binary_corrupt", "shared_library_missing"):
        with tempfile.TemporaryDirectory() as temporary:
            changed = Path(temporary) / "payload"
            shutil.copytree(payload, changed)
            document = copy.deepcopy(original)
            anchor = manifest_sha
            if name == "wrong_upstream":
                document["upstream"]["revision"] = "0"*40
            elif name == "changed_flags":
                document["build"]["flags"][1] = "-DGGML_NATIVE=ON"
            elif name == "missing_toolchain":
                document["build"]["toolchain"].pop("c_compiler")
            elif name == "binary_corrupt":
                target = changed / "bin/llama-server"
                raw = target.read_bytes()
                target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            else:
                library = next(item for item in document["native_files"] if ".so" in item)
                (changed / "bin" / library).unlink()
            if name in ("wrong_upstream", "changed_flags", "missing_toolchain"):
                write(changed / "manifest.json", document)
                anchor = sha(changed / "manifest.json")
            reject(name, changed, anchor, expected, current_platform)
    return cases


def produce(args):
    work, out = args.work.resolve(), args.out.resolve()
    work.mkdir(parents=True)
    out.mkdir(parents=True)
    start = time.monotonic()
    timings = {}
    identity, host = expected_identity(), substrate()
    require(host["system"] == "Linux" and host["machine"] == "x86_64" and
            host["os_id"] == "ubuntu" and host["os_version"] == "24.04", "producer_platform")
    require(host["image_os"] and host["image_version"], "hosted_image_identity")
    upstream, build, payload = work / "upstream", work / "build", work / "payload"
    for command_args in (["git", "init", str(upstream)],
                         ["git", "-C", str(upstream), "remote", "add", "origin", UPSTREAM]):
        command(command_args)
    _, _, timings["source_fetch_s"] = command(
        ["git", "-C", str(upstream), "fetch", "--depth=1", "origin", REV], timeout=180,
        log=out / "source-fetch.log")
    command(["git", "-C", str(upstream), "checkout", "--detach", "FETCH_HEAD"])
    revision, _, _ = command(["git", "-C", str(upstream), "rev-parse", "HEAD"])
    require(revision.strip() == REV, "checked_out_source")
    _, _, timings["configure_s"] = command(
        ["cmake", "-S", str(upstream), "-B", str(build), *FLAGS], timeout=180, log=out / "configure.log")
    _, _, timings["build_s"] = command(
        ["cmake", "--build", str(build), "--target", "llama-server", "-j", "2"],
        timeout=1200, log=out / "build.log")
    values = cache_values(build / "CMakeCache.txt")
    require({key: values.get(key) for key in EFFECTIVE} == EFFECTIVE, "effective_cmake_flags")
    toolchain = {name: tool_identity(values[key]) for name, key in (
        ("c_compiler", "CMAKE_C_COMPILER"), ("cxx_compiler", "CMAKE_CXX_COMPILER"), ("linker", "CMAKE_LINKER"))}
    toolchain["cmake"] = tool_identity(shutil.which("cmake"))
    bin_dir = build / "bin"
    native_files = ["llama-server"] + sorted(path.name for path in bin_dir.glob("*.so*") if path.is_file())
    require(len(native_files) > 1, "project_shared_libraries_required")
    package_started = time.monotonic()
    (payload / "bin").mkdir(parents=True)
    for name in native_files:
        source = bin_dir / name
        require(source.resolve().is_relative_to(build.resolve()), "project_binary_escape")
        target = payload / "bin" / name
        shutil.copyfile(source, target)
        target.chmod(normalized_mode(source))
    (payload / "notices").mkdir()
    shutil.copyfile(upstream / "LICENSE", payload / "notices/llama.cpp-LICENSE")
    dependency_contract = dependencies(bin_dir, native_files, out / "ldd")
    producer_probes = probes(bin_dir, out)
    manifest = {
        "schema": SCHEMA, "scope": "SAME_SUBSTRATE_CLI_ONLY",
        "producer": identity, "upstream": {"url": UPSTREAM, "revision": REV},
        "platform": host, "native_files": native_files,
        "build": {"flags": FLAGS, "effective": EFFECTIVE, "parallel_jobs": 2,
                  "toolchain": toolchain, "cmake_cache_sha256": sha(build / "CMakeCache.txt")},
        "dependencies": dependency_contract, "files": inventory(payload),
        "producer_probes": producer_probes,
    }
    write(payload / "manifest.json", manifest)
    archive_path = out / "native-build-reuse.tar"
    archive_path.write_bytes(build_layer(payload))
    shutil.copyfile(payload / "manifest.json", out / "manifest.json")
    shutil.copyfile(build / "CMakeCache.txt", out / "CMakeCache.txt")
    timings["package_and_producer_probe_s"] = time.monotonic() - package_started
    timings["producer_command_total_s"] = time.monotonic() - start
    if args.clock:
        clock = json.loads(args.clock.read_bytes())
        timings["setup_before_produce_s"] = start - clock["job_started_s"]
        timings["job_interval_before_upload_s"] = time.monotonic() - clock["job_started_s"]
    report = {"schema": "native-build-reuse-producer-receipt/v1", "status": "PRODUCED",
              "manifest_sha256": sha(out / "manifest.json"), "tar_sha256": sha(archive_path),
              "tar_bytes": archive_path.stat().st_size, "producer": manifest["producer"],
              "timings": timings, "model_inference": False}
    if args.clock:
        report["clock_origin"] = clock
    write(out / "producer.json", report)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"manifest_sha256={report['manifest_sha256']}\ntar_sha256={report['tar_sha256']}\n")
    print(json.dumps(report))


def consume(args):
    started = time.monotonic()
    args.out.mkdir(parents=True)
    result = {"schema": "native-build-reuse-consumer-receipt/v1", "status": "FAIL",
              "consumer": args.consumer, "producer": expected_identity(), "model_inference": False}
    artifact_id = os.environ.get("NATIVE_ARTIFACT_ID")
    require(artifact_id is not None and artifact_id.isdigit(), "transport_artifact_identity")
    result["github_artifact_id"] = artifact_id
    result["github_artifact_digest"] = os.environ.get("NATIVE_ARTIFACT_DIGEST")
    timings = {}
    clock = None
    try:
        if args.clock:
            clock = json.loads(args.clock.read_bytes())
            result["clock_origin"] = clock
            timings["setup_before_download_s"] = clock["download_started_s"] - clock["job_started_s"]
            timings["download_action_and_step_transition_s"] = started - clock["download_started_s"]
        stage = time.monotonic()
        payload = args.out / "payload"
        safe_unpack(args.archive, payload, args.tar_sha256)
        host = substrate()
        manifest = validate_payload(payload, args.manifest_sha256, expected_identity(), host)
        timings["integrity_and_identity_verification_s"] = time.monotonic() - stage
        stage = time.monotonic()
        observed = dependencies(payload / "bin", manifest["native_files"], args.out / "ldd")
        result["observed_dependencies"] = observed
        result["dependency_changes"] = {
            scope: {"missing": sorted(set(manifest["dependencies"][scope]) - set(observed[scope])),
                    "unexpected": sorted(set(observed[scope]) - set(manifest["dependencies"][scope])),
                    "changed": sorted(name for name in set(observed[scope]) & set(manifest["dependencies"][scope])
                                      if observed[scope][name] != manifest["dependencies"][scope][name])}
            for scope in ("internal", "external", "graph")}
        require(observed == manifest["dependencies"], "dependency_contract_mismatch")
        timings["dependency_resolution_s"] = time.monotonic() - stage
        actual_probes = probes(payload / "bin", args.out)
        result["probe_output_digest_matches_producer"] = {
            name: all(actual_probes[name][field] == manifest["producer_probes"][name][field]
                      for field in ("stdout_sha256", "stderr_sha256"))
            for name in actual_probes}
        stage = time.monotonic()
        controls = fault_controls(payload, args.manifest_sha256, expected_identity(), host)
        timings["negative_controls_s"] = time.monotonic() - stage
        result.update(status="VERIFIED_SAME_SUBSTRATE_CLI", platform=host,
                      manifest_sha256=args.manifest_sha256, tar_sha256=args.tar_sha256,
                      native_binary_sha256=sha(payload / "bin/llama-server"),
                      dependencies=observed, probes=actual_probes, fault_controls=controls,
                      qualification="source-bound payload reuse, dependency closure and native CLI only")
    except Exception as exc:
        result["failure"] = type(exc).__name__ + ":" + str(exc)[:180]
        raise
    finally:
        timings["consumer_command_total_s"] = time.monotonic() - started
        if clock is not None:
            timings["job_interval_before_evidence_upload_s"] = time.monotonic() - clock["job_started_s"]
        result["timings"] = timings
        write(args.out / "consumer.json", result)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    producer = sub.add_parser("produce")
    producer.add_argument("--work", type=Path, required=True)
    producer.add_argument("--out", type=Path, required=True)
    producer.add_argument("--clock", type=Path)
    consumer = sub.add_parser("consume")
    consumer.add_argument("--archive", type=Path, required=True)
    consumer.add_argument("--manifest-sha256", required=True)
    consumer.add_argument("--tar-sha256", required=True)
    consumer.add_argument("--consumer", choices=("1", "2"), required=True)
    consumer.add_argument("--out", type=Path, required=True)
    consumer.add_argument("--clock", type=Path)
    args = parser.parse_args()
    (produce if args.mode == "produce" else consume)(args)


if __name__ == "__main__":
    main()

