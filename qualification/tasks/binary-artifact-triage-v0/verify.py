#!/usr/bin/env python3
"""Independent verifier for a public-safe cross-format RE triage anchor.

Validates evidence-based artifact classification, NOT semantic binary recovery.
All inputs are synthetic observations; no code is executed.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

EXPECTED = {
    "a01": ("PE32_PLUS_X86_64", "GHIDRA_STATIC", ("header_hex", "pe_signature_hex", "coff_machine_hex", "optional_header_magic_hex")),
    "a02": ("MACH_O_ARM64", "GHIDRA_STATIC", ("header_hex", "mach_cpu_type_hex")),
    "a03": ("ELF_AARCH64", "GHIDRA_STATIC", ("header_hex", "elf_class_hex", "elf_data_hex", "elf_machine_hex")),
    "a04": ("ANDROID_APK_CANDIDATE", "VERIFY_CONTAINER", ("header_hex", "archive_entries")),
    "a05": ("IOS_IPA_CANDIDATE", "VERIFY_CONTAINER", ("header_hex", "archive_entries")),
    "a06": ("UNKNOWN_RAW", "RECOVER_CONTEXT", ("header_hex", "other_metadata")),
    "a07": ("DEX", "DEX_ANALYSIS", ("header_hex",)),
    "a08": ("WASM", "WASM_ANALYSIS", ("header_hex",)),
}
SOURCE = Path(__file__).resolve().parent / "fixture" / "observations.json"


def pointer_get(doc: object, pointer: str) -> object:
    if not pointer.startswith("/"):
        raise ValueError("not a JSON pointer")
    obj = doc
    for token in pointer[1:].split("/"):
        if "~" in token:
            for k in range(len(token) - 1):
                if token[k] == "~" and token[k + 1] not in "01":
                    raise ValueError("bad JSON pointer escape")
        token = token.replace("~1", "/").replace("~0", "~")
        obj = obj[int(token)] if isinstance(obj, list) else obj[token]
    return obj


def check(candidate: Path) -> bool:
    try:
        source_bytes = SOURCE.read_bytes()
        fixture_bytes = (candidate / "observations.json").read_bytes()
        if fixture_bytes != source_bytes:
            return False
        observed = json.loads(fixture_bytes)
        output = json.loads((candidate / "classification.json").read_text(encoding="utf-8"))
        if set(output) != {"schema_version", "artifacts"} or type(output["schema_version"]) is not int or output["schema_version"] != 1:
            return False
        if set(output["artifacts"]) != set(EXPECTED):
            return False
        for aid, (klass, action, required_fields) in EXPECTED.items():
            item = output["artifacts"][aid]
            if set(item) != {"class", "next_action", "evidence_refs"}:
                return False
            if item["class"] != klass or item["next_action"] != action:
                return False
            refs = item["evidence_refs"]
            if not isinstance(refs, list) or not refs or any(not isinstance(v, str) for v in refs) or len(refs) != len(set(refs)):
                return False
            prefix = f"observations.json#/artifacts/{aid}/"
            present_fields = set()
            for ref in refs:
                if not ref.startswith(prefix):
                    return False
                pointer_get(observed, ref[len("observations.json#"):])
                present_fields.add(ref[len(prefix):])
            if not set(required_fields).issubset(present_fields):
                return False
        return True
    except (OSError, TypeError, ValueError, KeyError, IndexError, AttributeError):
        return False


def good_output() -> dict:
    return {"schema_version": 1, "artifacts": {
        aid: {"class": klass, "next_action": action,
              "evidence_refs": [f"observations.json#/artifacts/{aid}/{field}" for field in fields]}
        for aid, (klass, action, fields) in EXPECTED.items()
    }}


def self_test() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "observations.json").write_bytes(SOURCE.read_bytes())

        def write(value: dict) -> None:
            (root / "classification.json").write_text(json.dumps(value), encoding="utf-8")

        correct = good_output()
        write(correct)
        assert check(root), "known-good output rejected"
        bad = copy.deepcopy(correct)
        bad["artifacts"]["a06"]["class"] = "ELF_AARCH64"
        write(bad)
        assert not check(root), "invented architecture accepted"
        bad = copy.deepcopy(correct)
        bad["artifacts"]["a05"]["next_action"] = "GHIDRA_STATIC"
        write(bad)
        assert not check(root), "unverified container treated as runnable"
        bad = copy.deepcopy(correct)
        bad["artifacts"]["a03"]["evidence_refs"] = ["observations.json#/artifacts/a03/header_hex"]
        write(bad)
        assert not check(root), "missing architecture evidence accepted"
        bad = copy.deepcopy(correct)
        bad["artifacts"]["a02"]["evidence_refs"] = ["observations.json#/artifacts/a02/fabricated"]
        write(bad)
        assert not check(root), "fabricated pointer accepted"
        bad = copy.deepcopy(correct)
        bad["artifacts"]["a04"]["evidence_refs"] = ["observations.json#/artifacts/a05/archive_entries"]
        write(bad)
        assert not check(root), "cross-artifact evidence accepted"
        bad = copy.deepcopy(correct)
        bad["artifacts"]["a08"]["class"] = "DEX"
        write(bad)
        assert not check(root), "wrong format accepted"
        write(correct)
        (root / "observations.json").write_bytes(SOURCE.read_bytes() + b"\n")
        assert not check(root), "modified evidence accepted"
    print("PASS binary-artifact-triage-v0: positive + seven negative controls")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify.py <candidate-directory> | --self-test")
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
