#!/usr/bin/env python3
"""Deterministic verifier for the v2 unified-characterization reference task."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path


EXPECTED = "READY\n"


def verify(candidate: Path) -> tuple[bool, str]:
    target = candidate / "value.txt"
    if not target.is_file():
        return False, "value.txt is missing"
    actual = target.read_text(encoding="utf-8")
    if actual != EXPECTED:
        return False, f"value.txt mismatch: expected {EXPECTED!r}, got {actual!r}"
    return True, "ok"


def self_test() -> None:
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        good = root_path / "good"
        bad = root_path / "bad"
        good.mkdir()
        bad.mkdir()
        (good / "value.txt").write_text(EXPECTED, encoding="utf-8")
        (bad / "value.txt").write_text("READY", encoding="utf-8")

        good_ok, _ = verify(good)
        bad_ok, _ = verify(bad)
        if not good_ok:
            raise SystemExit("self-test failed: known-good candidate was rejected")
        if bad_ok:
            raise SystemExit("self-test failed: known-bad candidate was accepted")
        print("PASS verifier accepts known-good and rejects known-bad")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if args.candidate is None:
        parser.error("candidate path is required unless --self-test is used")

    ok, message = verify(args.candidate)
    print(("PASS " if ok else "FAIL ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
